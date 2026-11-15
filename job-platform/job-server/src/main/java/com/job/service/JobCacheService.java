package com.job.service;

import com.job.cache.CachedJobDetail;
import com.job.vo.JobVO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.cache.Cache;
import org.springframework.cache.CacheManager;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.util.Collection;
import java.util.concurrent.ThreadLocalRandom;

/**
 * 岗位缓存的读写与清理入口 —— 把所有缓存细节收在一处。
 *
 * <h3>为什么需要它（而不是全用 {@code @CacheEvict}）</h3>
 *
 * {@code @CacheEvict} 只管得住**被 Spring 代理的方法**。本项目里有两条写入路径：
 *
 * <pre>
 *   ① 管理端 → JobServiceImpl.update()/startOrStop()/deleteBatch()
 *   ② 爬虫   → JobCrawlerService.saveJob() → jobMapper.refreshCrawlContent()
 *              → 直接调 Mapper、根本没经过 Service 代理 → 注解不会触发 ❌
 * </pre>
 *
 * ②那条路径原来**不清缓存**，于是 {@code job:detail:{id}} 会一直是爬虫改之前的
 * 旧描述，最长脏到 TTL 过期。所以这里统一提供清理入口，两条路径都调用它。
 *
 * <h3>两个缓存的关系</h3>
 * <ul>
 *   <li>{@code job:detail} —— 逻辑过期信封 {@link CachedJobDetail}，**物理上不过期**</li>
 *   <li>{@code job:detail:null} —— **空标记**，TTL 60 秒（见 {@code #markNull}）</li>
 * </ul>
 *
 * 两个 key 都用岗位 id。清理时必须**两个一起清**，否则会出现
 * "数据缓存清了，但空标记还在 → 岗位明明存在却一直报不存在"。
 *
 * <h3>刷新代际（generation）</h3>
 * 异步刷新是"读库 → 写缓存"两段，中间可能发生更新/删除/爬虫改写。
 * 每次清理缓存就 {@code INCR} 一个按 id 的代际计数；刷新线程在**读库前**记下代际，
 * 写回前再比对，不一致就放弃写入。这样能挡掉绝大多数"慢刷新把旧数据写回去"的情况。
 * （比对和写入不是原子的，极端情况下仍可能漏网，这一点不夸大。）
 */
@Service
@Slf4j
public class JobCacheService {

    /** 岗位详情缓存名。 */
    public static final String CACHE_JOB_DETAIL = "job:detail";

    /**
     * 缓存穿透防护用的「空标记」缓存名。
     * 必须和 {@code RedisConfiguration} 里注册的 cache 名一致（那里给了 60 秒 TTL）。
     */
    public static final String CACHE_JOB_DETAIL_NULL = "job:detail:null";

    /** 空标记的值，内容无所谓（只判断"有没有这个 key"）。 */
    private static final String NULL_MARKER = "1";

    /** 逻辑过期时间基准：10 分钟，再加 ±20% 抖动，避免一批 key 同时到点刷新。 */
    private static final Duration LOGICAL_TTL = Duration.ofMinutes(10);

    private static final double LOGICAL_TTL_JITTER_RATIO = 0.2;

    /** 刷新代际 key 前缀；清理缓存时自增。 */
    private static final String GENERATION_PREFIX = "job:detail:gen:";

    /** 代际 key 的保留时间：远长于任何一次刷新的耗时即可。 */
    private static final Duration GENERATION_TTL = Duration.ofDays(1);

    @Autowired
    private CacheManager cacheManager;
    @Autowired
    private StringRedisTemplate stringRedisTemplate;

    // ────────────────────────── 读 ──────────────────────────

    /**
     * 读岗位详情缓存信封。
     *
     * <p>兼容改造前写入的裸 {@link JobVO}：当成"已逻辑过期"返回。
     * 这样上线后老缓存还能继续服务一次，同时自然触发一次后台刷新把它换成新格式，
     * 不需要手工清 Redis。
     *
     * @return 未命中返回 {@code null}
     */
    public CachedJobDetail getCachedDetail(Long id) {
        if (id == null) {
            return null;
        }
        Cache cache = cacheManager.getCache(CACHE_JOB_DETAIL);
        if (cache == null) {
            return null;
        }
        try {
            Cache.ValueWrapper wrapper = cache.get(id);
            if (wrapper == null) {
                return null;
            }
            Object value = wrapper.get();
            if (value instanceof CachedJobDetail) {
                return (CachedJobDetail) value;
            }
            if (value instanceof JobVO) {
                // 老格式：没有逻辑过期时间，视为陈旧数据，触发一次刷新即可升级
                return new CachedJobDetail((JobVO) value, 0L, 0L);
            }
            return null;
        } catch (Exception e) {
            // 反序列化失败（比如改了字段、旧缓存对不上）不能把请求打挂，
            // 当成未命中处理，让调用方回源并覆盖掉这条坏缓存。
            log.warn("读取岗位缓存失败 {}::{}（按未命中处理）：{}",
                    CACHE_JOB_DETAIL, id, e.getMessage());
            return null;
        }
    }

    /**
     * 判断该 id 是否被标记为"确认不存在"。
     *
     * <p>这就是**防缓存穿透**的核心：查库发现没有 → 打一个短 TTL 的空标记。
     */
    public boolean isNullMarked(Long id) {
        if (id == null) {
            return false;
        }
        Cache cache = cacheManager.getCache(CACHE_JOB_DETAIL_NULL);
        if (cache == null) {
            return false;
        }
        try {
            return cache.get(id) != null;
        } catch (Exception e) {
            log.warn("读取空标记失败 {}::{}：{}", CACHE_JOB_DETAIL_NULL, id, e.getMessage());
            return false;
        }
    }

    // ────────────────────────── 写 ──────────────────────────

    /**
     * 写入详情缓存，并把逻辑过期时间重置为"现在 + 10 分钟（±20%）"。
     *
     * @param version 数据版本（岗位 updateTime 毫秒）；调用方保证它来自这次读库
     */
    public void putDetail(Long id, JobVO vo, long version) {
        if (id == null || vo == null) {
            return;
        }
        Cache cache = cacheManager.getCache(CACHE_JOB_DETAIL);
        if (cache == null) {
            return;
        }
        long expireAt = System.currentTimeMillis() + jitteredLogicalTtl();
        try {
            cache.put(id, new CachedJobDetail(vo, expireAt, version));
            // 数据已存在，之前可能残留的空标记要清掉，否则会被误判为不存在
            evictOne(CACHE_JOB_DETAIL_NULL, id, false);
        } catch (Exception e) {
            log.warn("写入岗位缓存失败 {}::{}：{}", CACHE_JOB_DETAIL, id, e.getMessage());
            throw e;
        }
    }

    /**
     * 查过数据库确认岗位不存在：清掉可能残留的旧详情，再打空标记。
     *
     * <p>只打空标记是不够的 —— 读取时"先看详情缓存"，旧的正向缓存会一直命中，
     * 删除操作就永远表现不出来。
     */
    public void markMissing(Long id) {
        if (id == null) {
            return;
        }
        evictOne(CACHE_JOB_DETAIL, id, false);
        markNull(id);
    }

    /**
     * 给一个"确实不存在"的 id 打空标记（防止缓存穿透）。
     *
     * <p>TTL 只有 60 秒（见 {@code RedisConfiguration}）—— 因为数据库是会变的，
     * 这个 id 过一会儿可能就被创建出来了。空标记留太久会误杀真实数据。
     */
    public void markNull(Long id) {
        if (id == null) {
            return;
        }
        Cache cache = cacheManager.getCache(CACHE_JOB_DETAIL_NULL);
        if (cache == null) {
            return;
        }
        try {
            cache.put(id, NULL_MARKER);
        } catch (Exception e) {
            log.warn("写入空标记失败 {}::{}：{}", CACHE_JOB_DETAIL_NULL, id, e.getMessage());
        }
    }

    // ────────────────────────── 代际 ──────────────────────────

    /** 读取当前刷新代际；不存在按 0，Redis 失败则由回源熔断与旧值降级处理。 */
    public long generation(Long id) {
        if (id == null) {
            return 0L;
        }
        try {
            String value = stringRedisTemplate.opsForValue().get(GENERATION_PREFIX + id);
            return value == null ? 0L : Long.parseLong(value);
        } catch (Exception e) {
            log.warn("读取岗位缓存代际失败 {}：{}", id, e.getMessage());
            throw e;
        }
    }

    /**
     * 代际一致时写入缓存。
     *
     * @return true 表示写入；false 表示期间发生过更新/删除，放弃这次写回
     */
    public boolean putDetailIfGenerationUnchanged(Long id, JobVO vo, long version, long expectedGeneration) {
        long current = generation(id);
        if (current != expectedGeneration) {
            log.info("岗位 {} 缓存代际已变化（{} -> {}），放弃本次异步刷新写入", id, expectedGeneration, current);
            return false;
        }
        putDetail(id, vo, version);
        return true;
    }

    // ────────────────────────── 清 ──────────────────────────

    /**
     * 清除单个岗位的缓存 —— **详情和空标记一起清**，并推进刷新代际。
     *
     * <p>调用时机遵循 **Cache Aside**：**先更新数据库、再删缓存**。
     * 顺序反过来的话（先删缓存再写库），中间那段窗口里别的线程会把旧值读回缓存。
     *
     * @param jobId 岗位 id；为 null 时直接返回
     */
    public void evictDetail(Long jobId) {
        if (jobId == null) {
            return;
        }
        bumpGeneration(jobId);
        evictOne(CACHE_JOB_DETAIL, jobId, false);
        evictOne(CACHE_JOB_DETAIL_NULL, jobId, false);
    }

    /**
     * 批量清除岗位缓存（按 id 精确清，**不要**用 allEntries 全清）。
     *
     * <p>{@code allEntries = true} 会把整个 {@code job:detail} 缓存清空：
     * 删 3 个岗位却让几百个岗位的缓存全失效，之后集中回填、集中过期 ——
     * 反而制造了缓存雪崩的场景。
     *
     * @return 实际尝试清理的条数
     */
    public int evictDetails(Collection<Long> jobIds) {
        if (jobIds == null || jobIds.isEmpty()) {
            return 0;
        }
        int count = 0;
        for (Long id : jobIds) {
            if (id == null) {
                continue;
            }
            evictDetail(id);
            count++;
        }
        log.info("批量清除岗位缓存 {} 条", count);
        return count;
    }

    /** 清理时推进代际，让正在执行的异步刷新知道"我读到的可能是旧数据"。 */
    private void bumpGeneration(Long id) {
        try {
            String key = GENERATION_PREFIX + id;
            stringRedisTemplate.opsForValue().increment(key);
            stringRedisTemplate.expire(key, GENERATION_TTL);
        } catch (Exception e) {
            log.warn("推进岗位缓存代际失败 {}：{}", id, e.getMessage());
        }
    }

    /** 清一个 cache 里的一个 key，失败只告警不抛。 */
    private void evictOne(String cacheName, Long id, boolean warnWhenMissing) {
        Cache cache = cacheManager.getCache(cacheName);
        if (cache == null) {
            if (warnWhenMissing) {
                log.warn("缓存 {} 不存在，跳过清理（检查 cacheManager 配置）", cacheName);
            }
            return;
        }
        try {
            cache.evict(id);
        } catch (Exception e) {
            // 不抛出：写库已经成功，清缓存失败只影响新鲜度，不该让事务回滚。
            // 但必须告警，否则缓存脏了没人知道。
            log.warn("清除缓存失败 {}::{}：{}", cacheName, id, e.getMessage());
        }
    }

    /** 逻辑 TTL 加 ±20% 抖动：同一批岗位不会在同一刻集体到点刷新。 */
    private long jitteredLogicalTtl() {
        long base = LOGICAL_TTL.toMillis();
        long range = (long) (base * LOGICAL_TTL_JITTER_RATIO);
        long delta = ThreadLocalRandom.current().nextLong(-range, range + 1);
        return Math.max(1_000L, base + delta);
    }
}
