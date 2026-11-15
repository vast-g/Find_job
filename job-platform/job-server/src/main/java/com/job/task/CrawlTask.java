package com.job.task;

import com.job.properties.CrawlProperties;
import com.job.service.JobCrawlerService;
import com.job.utils.RedisLockHelper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.Duration;

@Component
@Slf4j
public class CrawlTask {

    /**
     * 爬虫任务的分布式锁名。
     *
     * <p>为什么需要：{@code @Scheduled} 是**每个实例各自执行**的。如果部署两个实例，
     * 同一个 cron 到点时两边会同时开始爬 —— 同一批岗位被爬两遍，
     * 白白浪费一倍请求，也更容易被源站风控。
     *
     * <p>加一把 Redis 分布式锁，让同一时刻只有一个实例在爬，另一个直接跳过本轮。
     */
    private static final String LOCK_CRAWL = "job:crawl";

    /**
     * 锁的 TTL —— 必须**明显大于一次完整爬取的耗时**（多页 + 每页 sleep 500ms），
     * 否则锁会在爬取中途过期，另一个实例就能进来一起爬，锁等于没加。
     *
     * <p>代价是：如果进程爬到一半崩了，锁要等 TTL 到期才释放（最长 30 分钟）。
     * 对"每天跑一次"的定时任务完全可以接受；
     * 如果需要"崩溃后立刻可重入"，就要上 Redisson 的看门狗自动续期。
     */
    private static final Duration LOCK_TTL = Duration.ofMinutes(30);

    @Autowired
    private CrawlProperties crawlProperties;
    @Autowired
    private JobCrawlerService jobCrawlerService;
    @Autowired
    private RedisLockHelper redisLockHelper;

    @Scheduled(cron = "${job.crawl.cron:0 0 6 * * ?}")
    public void crawlJobs() {
        if (!crawlProperties.isEnabled()) {
            log.info("爬虫未启用（job.crawl.enabled=false）");
            return;
        }

        String token = redisLockHelper.tryLock(LOCK_CRAWL, LOCK_TTL);
        if (token == null) {
            // 没抢到锁 = 别的实例正在爬。**直接跳过本轮**，而不是排队等待 ——
            // 定时任务错过这一轮没关系，下一轮再来；排队反而会把任务堆积起来。
            log.info("本轮爬取跳过：已有实例正在执行（锁 {} 被占用）", LOCK_CRAWL);
            return;
        }

        try {
            log.info("获得爬取锁，开始执行");
            jobCrawlerService.crawl();
        } catch (Exception e) {
            // 爬虫失败不该让调度线程挂掉，记录后交给下一轮
            log.error("爬取任务执行失败：{}", e.getMessage(), e);
        } finally {
            // 一定要在 finally 释放：否则出错时锁要等 30 分钟才自动过期
            redisLockHelper.unlock(LOCK_CRAWL, token);
        }
    }
}
