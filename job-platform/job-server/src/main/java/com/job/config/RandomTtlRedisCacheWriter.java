package com.job.config;

import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.cache.CacheStatistics;
import org.springframework.data.redis.cache.CacheStatisticsCollector;
import org.springframework.data.redis.cache.RedisCacheWriter;

import java.time.Duration;
import java.util.concurrent.ThreadLocalRandom;

/**
 * 给缓存 TTL 加随机抖动的 {@link RedisCacheWriter} 装饰器 —— 防**缓存雪崩**。
 *
 * <h3>为什么需要它</h3>
 * 原来的配置是 {@code entryTtl(Duration.ofMinutes(10))}：**所有** cache 条目
 * 共用同一个固定 TTL。一旦出现"大批 key 在同一时刻被写入"的情况，它们就会
 * 在同一时刻集体过期，随后的并发请求会一起打到 MySQL —— 这就是缓存雪崩。
 *
 * <p>本项目里最容易触发的是 {@code deleteBatch}：它原来用
 * {@code @CacheEvict(allEntries = true)} 把整个 {@code job:detail} 缓存清空，
 * 之后这批岗位会被陆续重新请求、在几秒内集中写回缓存，10 分钟后集中过期。
 * （那个 allEntries 本身也是问题，见 {@code JobServiceImpl.deleteBatch} 的改动。）
 *
 * <h3>为什么用装饰器而不是改配置</h3>
 * Spring Data Redis 2.7 的 {@code RedisCacheConfiguration.entryTtl(...)} 只接受
 * 固定 {@code Duration}，没有"按 key 计算 TTL"的钩子
 * （{@code TtlFunction} 是更高版本才有的）。
 * 但 {@link RedisCacheWriter} 是缓存真正写 Redis 的地方，它的
 * {@code put(name, key, value, ttl)} 拿得到 ttl —— 在这里加抖动，
 * 对上层 {@code @Cacheable} 完全透明，注解一行都不用改。
 *
 * <h3>抖动幅度怎么定</h3>
 * 默认取 TTL 的 {@code jitterRatio}（20%），并限制不超过 TTL 的一半：
 * TTL 10 分钟 → 实际落在 8~12 分钟。这样即使一批 key 同时写入，
 * 过期时间也会被摊开在这 4 分钟的窗口里，不会"同时"打库。
 *
 * <p>TTL 为 null / 0 / 负数时原样透传（表示不过期），不硬加抖动 ——
 * 否则会把"永不过期"的 key 变成会过期，那是行为改变而不是防雪崩。
 */
@Slf4j
public class RandomTtlRedisCacheWriter implements RedisCacheWriter {

    /** 兜底下限：抖动幅度再小也至少这么多，否则起不到打散作用。 */
    private static final long MIN_JITTER_MS = 30_000L;

    private final RedisCacheWriter delegate;
    private final double jitterRatio;
    private final long minJitterMs;

    public RandomTtlRedisCacheWriter(RedisCacheWriter delegate,
                                     double jitterRatio,
                                     Duration minJitter) {
        this.delegate = delegate;
        this.jitterRatio = jitterRatio;
        this.minJitterMs = Math.max(MIN_JITTER_MS, minJitter == null ? 0L : minJitter.toMillis());
    }

    @Override
    public void put(String name, byte[] key, byte[] value, Duration ttl) {
        delegate.put(name, key, value, jittered(ttl));
    }

    @Override
    public byte[] get(String name, byte[] key) {
        return delegate.get(name, key);
    }

    @Override
    public byte[] putIfAbsent(String name, byte[] key, byte[] value, Duration ttl) {
        return delegate.putIfAbsent(name, key, value, jittered(ttl));
    }

    @Override
    public void remove(String name, byte[] key) {
        delegate.remove(name, key);
    }

    @Override
    public void clean(String name, byte[] pattern) {
        delegate.clean(name, pattern);
    }

    @Override
    public void clearStatistics(String name) {
        delegate.clearStatistics(name);
    }

    /** 父接口 {@code CacheStatisticsProvider} 要求的方法，直接透传。 */
    @Override
    public CacheStatistics getCacheStatistics(String cacheName) {
        return delegate.getCacheStatistics(cacheName);
    }

    @Override
    public RedisCacheWriter withStatisticsCollector(CacheStatisticsCollector collector) {
        return new RandomTtlRedisCacheWriter(
                delegate.withStatisticsCollector(collector), jitterRatio,
                Duration.ofMillis(minJitterMs));
    }

    /**
     * 把固定 TTL 变成"固定 TTL ± 抖动"。
     *
     * <p>抖动范围取 {@code max(下限, ttl * ratio)}，并且**不超过 ttl 的一半**，
     * 保证结果永远是正数、且不会因为抖动把 TTL 放大成离谱的值。
     */
    private Duration jittered(Duration ttl) {
        if (ttl == null || ttl.isZero() || ttl.isNegative()) {
            return ttl;
        }
        long base = ttl.toMillis();
        long range = Math.max(minJitterMs, (long) (base * jitterRatio));
        range = Math.min(range, base / 2);
        if (range <= 0) {
            return ttl;
        }
        long delta = ThreadLocalRandom.current().nextLong(-range, range + 1);
        long millis = Math.max(1_000L, base + delta);
        Duration result = Duration.ofMillis(millis);
        log.trace("缓存 TTL 抖动：{} -> {}", ttl, result);
        return result;
    }
}
