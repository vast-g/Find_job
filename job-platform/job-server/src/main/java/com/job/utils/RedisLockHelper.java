package com.job.utils;

import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.Collections;
import java.util.UUID;

/**
 * 基于 Redis 的简单分布式锁（SETNX + 唯一 token + Lua 安全释放）。
 *
 * <h3>为什么要自己写，而不是直接用 Redisson</h3>
 * 黑马点评里讲的是 Redisson，生产环境也确实推荐它（有看门狗自动续期、可重入）。
 * 但 Redisson 要额外引一个 starter，会接管 Spring 的 Redis 自动配置，
 * 对学生项目来说多一层风险。这里的场景都很简单（几秒内完成、
 * 不存在业务代码执行时间不可控的问题），用 SETNX 足够，而且**机制看得见**。
 *
 * <p>如果哪天要在锁里跑长任务（超过锁的 TTL），换成 Redisson 的
 * {@code RLock} —— 它的看门狗会在持有期间自动续期，避免"活干到一半锁过期、
 * 另一个线程进来重复干"。
 *
 * <h3>三个必须做对的地方</h3>
 * <ol>
 *   <li><b>加锁必须带 TTL</b>：否则拿到锁的进程崩了，这个 key 永远不释放，
 *       所有后来的请求全被卡死（死锁）。</li>
 *   <li><b>值必须是唯一 token</b>：不能写死 "1"。否则 A 的锁过期后 B 拿到锁，
 *       A 干完活去删锁，把 B 的锁删了 —— 锁就失效了。</li>
 *   <li><b>释放必须"先比对再删"</b>：比对和删除必须原子，所以要用 Lua。
 *       如果先 GET 再 DEL，中间这两步之间锁可能已经过期被别人拿走。</li>
 * </ol>
 *
 * <p>本类把这些都封装好了，调用方只要成对使用 {@link #tryLock} /
 * {@link #unlock}，并在 finally 里释放。
 */
@Component
@Slf4j
public class RedisLockHelper {

    /**
     * 释放锁的 Lua：只有值仍然是自己那个 token 时才删。
     * 用 Lua 是因为 Redis 单线程执行脚本 —— "比对 + 删除"不会被别的命令插队。
     */
    private static final DefaultRedisScript<Long> UNLOCK_SCRIPT = new DefaultRedisScript<>(
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
                    + "return redis.call('del', KEYS[1]) "
                    + "else return 0 end",
            Long.class);

    private static final String PREFIX = "lock:";

    @Autowired
    private StringRedisTemplate stringRedisTemplate;

    /**
     * 尝试获取锁，**立即返回**，不阻塞等待。
     *
     * <p>返回值为本次持有的唯一 token —— 释放锁时必须把它传回
     * {@link #unlock}，这样才不会被"删掉别人的锁"。
     *
     * <pre>{@code
     * String token = lockHelper.tryLock("job:rebuild:1", Duration.ofSeconds(5));
     * if (token != null) {
     *     try { ...重建缓存... } finally { lockHelper.unlock("job:rebuild:1", token); }
     * }
     * }</pre>
     *
     * @param key 业务锁名（不含前缀），内部会加 {@code lock:} 前缀
     * @param ttl 锁的存活时间，必须足以覆盖本次操作
     * @return 成功返回 token；没抢到返回 {@code null}
     */
    public String tryLock(String key, Duration ttl) {
        String token = UUID.randomUUID().toString();
        Boolean ok = stringRedisTemplate.opsForValue()
                .setIfAbsent(PREFIX + key, token, ttl);
        if (Boolean.TRUE.equals(ok)) {
            log.debug("加锁成功 {}", key);
            return token;
        }
        log.debug("加锁失败（已被占用）{}", key);
        return null;
    }

    /**
     * 释放锁。只有 token 和 Redis 里的值一致时才真正删除。
     *
     * @param key   业务锁名（不含前缀）
     * @param token {@link #tryLock} 写回的那个 token
     */
    public void unlock(String key, String token) {
        if (token == null || token.isEmpty()) {
            return;
        }
        try {
            Long released = stringRedisTemplate.execute(
                    UNLOCK_SCRIPT, Collections.singletonList(PREFIX + key), token);
            log.debug("释放锁 {} -> {}", key, released);
        } catch (Exception e) {
            // 释放失败不该让业务失败：锁有 TTL，最坏情况等它自己过期。
            // 但必须留日志，否则"锁泄漏"会变成看不见的问题。
            log.warn("释放锁 {} 失败（TTL 到期后会自动释放）：{}", key, e.getMessage());
        }
    }
}
