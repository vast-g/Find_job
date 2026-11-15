package com.job.config;

import com.fasterxml.jackson.annotation.JsonTypeInfo;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.databind.jsontype.impl.LaissezFaireSubTypeValidator;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cache.CacheManager;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.cache.RedisCacheConfiguration;
import org.springframework.data.redis.cache.RedisCacheManager;
import org.springframework.data.redis.cache.RedisCacheWriter;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.data.redis.serializer.GenericJackson2JsonRedisSerializer;
import org.springframework.data.redis.serializer.RedisSerializationContext;
import org.springframework.data.redis.serializer.StringRedisSerializer;

import java.time.Duration;
import java.util.HashMap;
import java.util.Map;

@Configuration
@Slf4j
public class RedisConfiguration {

    /**
     * 基准 TTL（加抖动之前）。
     *
     * <p>注意：这里的值只是"基准"，真正写入 Redis 的 TTL 会被
     * {@link RandomTtlRedisCacheWriter} 抖动成 8~12 分钟。
     */
    private static final Duration BASE_TTL = Duration.ofMinutes(10);

    /** TTL 抖动比例：±20%。见 {@link RandomTtlRedisCacheWriter}。 */
    private static final double TTL_JITTER_RATIO = 0.2;

    /** 逻辑过期缓存必须保留旧值，物理上不提前过期。 */
    private static final Duration NO_PHYSICAL_TTL = Duration.ZERO;

    @Bean
    /**
     * 初始化 RedisTemplate(第一种：动手写代码存取缓存)
     */
    public RedisTemplate<String, Object> redisTemplate(RedisConnectionFactory redisConnectionFactory) {
        log.info("初始化 RedisTemplate");
        RedisTemplate<String, Object> template = new RedisTemplate<>();
        template.setConnectionFactory(redisConnectionFactory);
        template.setKeySerializer(new StringRedisSerializer());
        return template;
    }

    @Bean
    /**
     * 初始化 CacheManager(第二种：使用 RedisCacheManager，只加一个注解，Spring Cache 框架帮你自动存取缓存)
     *
     * <p><b>防缓存雪崩</b>：这里的 {@code entryTtl} 是**基准 TTL**，实际写入时
     * 会经过 {@link RandomTtlRedisCacheWriter} 加 ±20% 的随机抖动
     * （10 分钟 → 8~12 分钟）。原来的写法是所有 key 共用同一个固定 TTL，
     * 只要有一批 key 集中在几秒内写入（比如批量删缓存后集中回填），
     * 它们就会在同一时刻集体过期、一起把 MySQL 打满。
     */
    public CacheManager cacheManager(RedisConnectionFactory redisConnectionFactory) {
        ObjectMapper objectMapper = new ObjectMapper();
        objectMapper.registerModule(new JavaTimeModule());
        objectMapper.disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);
        objectMapper.activateDefaultTyping(
                LaissezFaireSubTypeValidator.instance,
                ObjectMapper.DefaultTyping.NON_FINAL,
                JsonTypeInfo.As.PROPERTY);

        GenericJackson2JsonRedisSerializer serializer = new GenericJackson2JsonRedisSerializer(objectMapper);

        // 基准 TTL：抖动之前的值
        RedisCacheConfiguration config = RedisCacheConfiguration.defaultCacheConfig()
                .entryTtl(BASE_TTL)
                .serializeKeysWith(RedisSerializationContext.SerializationPair.fromSerializer(new StringRedisSerializer()))
                .serializeValuesWith(RedisSerializationContext.SerializationPair.fromSerializer(serializer));

        // 用装饰过的 writer 建 CacheManager：TTL 在真正写 Redis 的那一刻才加抖动，
        // @Cacheable 注解不需要任何改动。
        RedisCacheWriter jitterWriter = new RandomTtlRedisCacheWriter(
                RedisCacheWriter.nonLockingRedisCacheWriter(redisConnectionFactory),
                TTL_JITTER_RATIO,
                Duration.ofSeconds(30));

        // ── 防缓存穿透用的「空标记」缓存，单独给一个短 TTL ──
        //
        // 为什么短：空标记表示"这个 id 现在确实不存在"。但数据库是会被写入的
        // （爬虫新增岗位、管理员手动建岗），id 可能过一会儿就有了。
        // 空标记留太久会把"真实存在"的岗位挡掉，所以只留 60 秒
        // （抖动后 48~72 秒），宁可偶尔多查一次库，也不要长期误判。
        //
        // 注意：这个 cache 名必须和 JobCacheService.CACHE_JOB_DETAIL_NULL 一致。
        Map<String, RedisCacheConfiguration> perCache = new HashMap<>();
        perCache.put("job:detail", config.entryTtl(NO_PHYSICAL_TTL));
        perCache.put("category:list", config.entryTtl(NO_PHYSICAL_TTL));
        perCache.put("job:detail:null", config.entryTtl(Duration.ofSeconds(60)));

        return RedisCacheManager.builder(jitterWriter)
                .cacheDefaults(config)
                .withInitialCacheConfigurations(perCache)
                .build();
    }
}
