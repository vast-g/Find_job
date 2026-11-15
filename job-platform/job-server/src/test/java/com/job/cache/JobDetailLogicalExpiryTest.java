package com.job.cache;

import com.job.entity.Job;
import com.job.mapper.CompanyMapper;
import com.job.mapper.JobMapper;
import com.job.service.JobCacheService;
import com.job.service.impl.JobServiceImpl;
import com.job.utils.RedisLockHelper;
import com.job.vo.JobVO;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.cache.Cache;
import org.springframework.cache.CacheManager;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.Executor;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/** 岗位详情：逻辑过期返回旧值 + 单次后台刷新；冷启动仍走互斥锁。 */
class JobDetailLogicalExpiryTest {

    private final List<Runnable> tasks = new ArrayList<>();

    private JobServiceImpl service(JobMapper jobs, JobCacheService cache, RedisLockHelper lock) {
        JobServiceImpl service = new JobServiceImpl();
        CompanyMapper companies = mock(CompanyMapper.class);
        Executor executor = command -> tasks.add(command);
        ReflectionTestUtils.setField(service, "jobMapper", jobs);
        ReflectionTestUtils.setField(service, "companyMapper", companies);
        ReflectionTestUtils.setField(service, "jobCacheService", cache);
        ReflectionTestUtils.setField(service, "redisLockHelper", lock);
        ReflectionTestUtils.setField(service, "cacheRefreshExecutor", executor);
        return service;
    }

    private Job job(long id) {
        return Job.builder().id(id).title("Java").companyId(9L)
                .updateTime(LocalDateTime.of(2026, 1, 1, 0, 0)).build();
    }

    @AfterEach
    void noLeftoverTasks() {
        tasks.clear();
    }

    @Test
    void logicallyExpiredDetailReturnsStaleImmediatelyAndRefreshesOnlyOnce() {
        JobMapper jobs = mock(JobMapper.class);
        JobCacheService cache = mock(JobCacheService.class);
        RedisLockHelper lock = mock(RedisLockHelper.class);
        JobVO stale = JobVO.builder().id(1L).title("old title").build();
        when(cache.getCachedDetail(1L))
                .thenReturn(new CachedJobDetail(stale, System.currentTimeMillis() - 60_000, 5L));
        JobServiceImpl service = service(jobs, cache, lock);

        // 并发读 20 次：全部立刻拿到旧值，且本实例只排队一个刷新任务
        for (int i = 0; i < 20; i++) {
            assertEquals("old title", service.getById(1L).getTitle());
        }
        assertEquals(1, tasks.size());
        verifyNoInteractions(jobs);
        verify(cache, never()).putDetail(anyLong(), any(), anyLong());
    }

    @Test
    void freshDetailIsServedWithoutAnyRefreshOrDatabaseRead() {
        JobMapper jobs = mock(JobMapper.class);
        JobCacheService cache = mock(JobCacheService.class);
        JobVO fresh = JobVO.builder().id(2L).title("fresh").build();
        when(cache.getCachedDetail(2L))
                .thenReturn(new CachedJobDetail(fresh, System.currentTimeMillis() + 600_000, 1L));
        JobServiceImpl service = service(jobs, cache, mock(RedisLockHelper.class));

        assertEquals("fresh", service.getById(2L).getTitle());
        assertTrue(tasks.isEmpty());
        verifyNoInteractions(jobs);
    }

    @Test
    void coldMissStillRebuildsWithMutualExclusionLock() {
        JobMapper jobs = mock(JobMapper.class);
        JobCacheService cache = mock(JobCacheService.class);
        RedisLockHelper lock = mock(RedisLockHelper.class);
        when(cache.getCachedDetail(3L)).thenReturn(null);
        when(cache.isNullMarked(3L)).thenReturn(false);
        when(lock.tryLock(startsWith("job:detail:rebuild:"), any(Duration.class))).thenReturn("token");
        when(cache.generation(3L)).thenReturn(7L);
        when(jobs.getById(3L)).thenReturn(job(3L));
        JobServiceImpl service = service(jobs, cache, lock);

        assertEquals("Java", service.getById(3L).getTitle());
        verify(cache).putDetailIfGenerationUnchanged(eq(3L), any(JobVO.class), anyLong(), eq(7L));
        verify(lock).unlock(startsWith("job:detail:rebuild:"), eq("token"));
    }

    @Test
    void backgroundRefreshMarksMissingAndNeverServesDeletedJobForever() {
        JobMapper jobs = mock(JobMapper.class);
        JobCacheService cache = mock(JobCacheService.class);
        RedisLockHelper lock = mock(RedisLockHelper.class);
        JobVO stale = JobVO.builder().id(4L).title("stale").build();
        when(cache.getCachedDetail(4L))
                .thenReturn(new CachedJobDetail(stale, System.currentTimeMillis() - 1_000, 2L));
        when(lock.tryLock(startsWith("job:detail:rebuild:"), any(Duration.class))).thenReturn("token");
        when(cache.generation(4L)).thenReturn(3L);
        when(jobs.getById(4L)).thenReturn(null);
        JobServiceImpl service = service(jobs, cache, lock);

        service.getById(4L);
        tasks.get(0).run();

        verify(cache).markMissing(4L);
        verify(cache, never()).putDetailIfGenerationUnchanged(anyLong(), any(), anyLong(), anyLong());
        verify(lock).unlock(startsWith("job:detail:rebuild:"), eq("token"));
    }

    @Test
    void refreshAbortsWhenGenerationMovedOn() {
        JobMapper jobs = mock(JobMapper.class);
        JobCacheService cache = mock(JobCacheService.class);
        RedisLockHelper lock = mock(RedisLockHelper.class);
        JobVO stale = JobVO.builder().id(5L).title("stale").build();
        when(cache.getCachedDetail(5L))
                .thenReturn(new CachedJobDetail(stale, System.currentTimeMillis() - 1_000, 2L));
        when(lock.tryLock(startsWith("job:detail:rebuild:"), any(Duration.class))).thenReturn("token");
        when(cache.generation(5L)).thenReturn(1L);
        when(jobs.getById(5L)).thenReturn(job(5L));
        when(cache.putDetailIfGenerationUnchanged(eq(5L), any(JobVO.class), anyLong(), eq(1L)))
                .thenReturn(false);
        JobServiceImpl service = service(jobs, cache, lock);

        service.getById(5L);
        tasks.get(0).run();

        verify(cache).putDetailIfGenerationUnchanged(eq(5L), any(JobVO.class), anyLong(), eq(1L));
        // 刷新期间发生过更新：写入被拒绝，不会用旧数据覆盖
        verify(cache, never()).putDetail(anyLong(), any(), anyLong());
    }

    @Test
    void queuedRefreshSkipsDatabaseWhenAnotherRequestAlreadyRefreshedCache() {
        JobMapper jobs = mock(JobMapper.class);
        JobCacheService cache = mock(JobCacheService.class);
        RedisLockHelper lock = mock(RedisLockHelper.class);
        JobVO old = JobVO.builder().id(10L).title("old").build();
        JobVO fresh = JobVO.builder().id(10L).title("fresh").build();
        when(cache.getCachedDetail(10L)).thenReturn(
                new CachedJobDetail(old, System.currentTimeMillis() - 1000, 1),
                new CachedJobDetail(fresh, System.currentTimeMillis() + 600_000, 2));
        when(lock.tryLock("job:detail:rebuild:10", Duration.ofSeconds(10))).thenReturn("token");
        JobServiceImpl service = service(jobs, cache, lock);
        assertSame(old, service.getById(10L));
        tasks.get(0).run();
        verifyNoInteractions(jobs);
        verify(cache, never()).generation(anyLong());
        verify(lock).unlock("job:detail:rebuild:10", "token");
        assertSame(fresh, service.getById(10L));
        assertEquals(1, tasks.size());
    }

    @Test
    void queuedRefreshSkipsDatabaseWhenJobWasAlreadyMarkedMissing() {
        JobMapper jobs = mock(JobMapper.class);
        JobCacheService cache = mock(JobCacheService.class);
        RedisLockHelper lock = mock(RedisLockHelper.class);
        JobVO old = JobVO.builder().id(11L).build();
        when(cache.getCachedDetail(11L)).thenReturn(
                new CachedJobDetail(old, System.currentTimeMillis() - 1000, 1), null);
        when(cache.isNullMarked(11L)).thenReturn(true);
        when(lock.tryLock("job:detail:rebuild:11", Duration.ofSeconds(10))).thenReturn("token");
        JobServiceImpl service = service(jobs, cache, lock);
        assertSame(old, service.getById(11L));
        tasks.get(0).run();
        verifyNoInteractions(jobs);
        verify(lock).unlock("job:detail:rebuild:11", "token");
        assertThrows(com.job.exception.JobBusinessException.class, () -> service.getById(11L));
    }

    @Test
    void asyncRefreshCannotEnterWhileSynchronousRebuildHoldsSameJobLock() throws Exception {
        JobMapper jobs = mock(JobMapper.class);
        JobCacheService cache = mock(JobCacheService.class);
        RedisLockHelper lock = mock(RedisLockHelper.class);
        JobVO old = JobVO.builder().id(12L).title("old").build();
        java.util.concurrent.atomic.AtomicReference<CachedJobDetail> value =
                new java.util.concurrent.atomic.AtomicReference<>(
                        new CachedJobDetail(old, System.currentTimeMillis() - 1000, 1));
        when(cache.getCachedDetail(12L)).thenAnswer(invocation -> value.get());
        java.util.concurrent.atomic.AtomicBoolean held = new java.util.concurrent.atomic.AtomicBoolean();
        when(lock.tryLock(anyString(), any(Duration.class))).thenAnswer(invocation -> {
            assertEquals("job:detail:rebuild:12", invocation.getArgument(0));
            return held.compareAndSet(false, true) ? "token" : null;
        });
        doAnswer(invocation -> { held.set(false); return null; })
                .when(lock).unlock("job:detail:rebuild:12", "token");
        java.util.concurrent.CountDownLatch querying = new java.util.concurrent.CountDownLatch(1);
        java.util.concurrent.CountDownLatch finish = new java.util.concurrent.CountDownLatch(1);
        when(jobs.getById(12L)).thenAnswer(invocation -> {
            querying.countDown();
            assertTrue(finish.await(5, java.util.concurrent.TimeUnit.SECONDS));
            return job(12L);
        });
        JobServiceImpl service = service(jobs, cache, lock);
        assertSame(old, service.getById(12L)); // queue background work without running it
        value.set(null); // simulate invalidation before that task starts
        java.util.concurrent.ExecutorService worker = java.util.concurrent.Executors.newSingleThreadExecutor();
        try {
            java.util.concurrent.Future<JobVO> cold = worker.submit(() -> service.getById(12L));
            assertTrue(querying.await(5, java.util.concurrent.TimeUnit.SECONDS));
            tasks.get(0).run(); // shared lock is held by the synchronous path
            verify(jobs, times(1)).getById(12L);
            finish.countDown();
            assertEquals("Java", cold.get(5, java.util.concurrent.TimeUnit.SECONDS).getTitle());
            verify(lock, times(2)).tryLock("job:detail:rebuild:12", Duration.ofSeconds(10));
            verify(lock, times(1)).unlock("job:detail:rebuild:12", "token");
            assertFalse(held.get());
        } finally {
            finish.countDown();
            worker.shutdownNow();
            assertTrue(worker.awaitTermination(5, java.util.concurrent.TimeUnit.SECONDS));
        }
    }

    @Test
    void legacyBareJobVoIsTreatedAsStaleAndServedOnceForUpgrade() {
        CacheManager cacheManager = mock(CacheManager.class);
        Cache detail = mock(Cache.class);
        Cache.ValueWrapper wrapper = mock(Cache.ValueWrapper.class);
        JobVO legacy = JobVO.builder().id(8L).title("legacy").build();
        when(cacheManager.getCache(JobCacheService.CACHE_JOB_DETAIL)).thenReturn(detail);
        when(detail.get(8L)).thenReturn(wrapper);
        when(wrapper.get()).thenReturn(legacy);
        JobCacheService cache = new JobCacheService();
        ReflectionTestUtils.setField(cache, "cacheManager", cacheManager);

        CachedJobDetail cached = cache.getCachedDetail(8L);
        assertNotNull(cached);
        assertEquals("legacy", cached.getData().getTitle());
        // 没有逻辑过期时间 → 视为陈旧，上线后自然触发一次刷新升级格式
        assertTrue(cached.getExpireAt() <= System.currentTimeMillis());
    }

    @Test
    void jitterWriterLeavesPersistentLogicalCachesWithoutPhysicalExpiry() {
        org.springframework.data.redis.cache.RedisCacheWriter delegate =
                mock(org.springframework.data.redis.cache.RedisCacheWriter.class);
        com.job.config.RandomTtlRedisCacheWriter writer =
                new com.job.config.RandomTtlRedisCacheWriter(delegate, 0.2, Duration.ofSeconds(30));

        writer.put("job:detail", new byte[]{1}, new byte[]{2}, Duration.ZERO);
        verify(delegate).put("job:detail", new byte[]{1}, new byte[]{2}, Duration.ZERO);

        writer.put("job:detail", new byte[]{3}, new byte[]{4}, Duration.ofMinutes(10));
        verify(delegate).put(eq("job:detail"), eq(new byte[]{3}), eq(new byte[]{4}),
                argThat(ttl -> ttl.toMinutes() >= 8 && ttl.toMinutes() <= 12));
    }

    @Test
    void redisWriteFailureIsPropagatedWithoutEvictingOldValue() {
        CacheManager manager = mock(CacheManager.class);
        Cache detail = mock(Cache.class);
        when(manager.getCache(JobCacheService.CACHE_JOB_DETAIL)).thenReturn(detail);
        IllegalStateException failure = new IllegalStateException("Redis unavailable");
        doThrow(failure).when(detail).put(anyLong(), any());
        JobCacheService cache = new JobCacheService();
        ReflectionTestUtils.setField(cache, "cacheManager", manager);
        assertSame(failure, assertThrows(IllegalStateException.class,
                () -> cache.putDetail(1L, JobVO.builder().id(1L).build(), 1L)));
        verify(detail, never()).evict(any());
    }

    @Test
    void cacheServiceRefusesWriteWhenGenerationChangedAndClearsNullMarkerOnWrite() {
        CacheManager cacheManager = mock(CacheManager.class);
        Cache detail = mock(Cache.class);
        Cache nullCache = mock(Cache.class);
        when(cacheManager.getCache(JobCacheService.CACHE_JOB_DETAIL)).thenReturn(detail);
        when(cacheManager.getCache(JobCacheService.CACHE_JOB_DETAIL_NULL)).thenReturn(nullCache);
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        @SuppressWarnings("unchecked")
        ValueOperations<String, String> values = mock(ValueOperations.class);
        when(redis.opsForValue()).thenReturn(values);
        when(values.get("job:detail:gen:6")).thenReturn("9");

        JobCacheService cache = new JobCacheService();
        ReflectionTestUtils.setField(cache, "cacheManager", cacheManager);
        ReflectionTestUtils.setField(cache, "stringRedisTemplate", redis);

        JobVO vo = JobVO.builder().id(6L).title("fresh").build();
        assertFalse(cache.putDetailIfGenerationUnchanged(6L, vo, 10L, 8L));
        verify(detail, never()).put(anyLong(), any());

        when(values.get("job:detail:gen:7")).thenReturn("8");
        assertTrue(cache.putDetailIfGenerationUnchanged(7L, vo, 10L, 8L));
        verify(detail).put(eq(7L), argThat(value -> {
            CachedJobDetail cached = (CachedJobDetail) value;
            return cached.getData() == vo && cached.getVersion() == 10L
                    && cached.getExpireAt() > System.currentTimeMillis();
        }));
        verify(nullCache).evict(7L);
    }
}
