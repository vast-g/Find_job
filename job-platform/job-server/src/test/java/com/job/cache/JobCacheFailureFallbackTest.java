package com.job.cache;

import com.job.config.CacheRefreshExecutorConfiguration.DiscardAwareTask;
import com.job.entity.Job;
import com.job.exception.JobBusinessException;
import com.job.mapper.CompanyMapper;
import com.job.mapper.JobMapper;
import com.job.service.JobCacheService;
import com.job.service.impl.JobServiceImpl;
import com.job.utils.RedisLockHelper;
import com.job.vo.JobVO;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class JobCacheFailureFallbackTest {

    @Test
    void failedBackgroundDatabaseReadUnlocksAndAllowsNextRequestToSubmitAgain() {
        Fixture fixture = new Fixture();
        JobVO stale = fixture.cacheStale(1L, Duration.ofMinutes(1));
        when(fixture.locks.tryLock(eq("job:detail:rebuild:1"), any(Duration.class))).thenReturn("refresh-token");
        when(fixture.jobs.getById(1L)).thenThrow(new IllegalStateException("database unavailable"));

        assertSame(stale, fixture.service.getById(1L));
        assertEquals(1, fixture.tasks.size());
        verifyNoInteractions(fixture.jobs, fixture.locks);
        assertDoesNotThrow(() -> fixture.tasks.get(0).run());
        verify(fixture.locks).unlock("job:detail:rebuild:1", "refresh-token");

        assertSame(stale, fixture.service.getById(1L));
        assertEquals(2, fixture.tasks.size(), "failed refresh must clear local deduplication");
        assertDoesNotThrow(() -> fixture.tasks.get(1).run());
        verify(fixture.jobs, times(2)).getById(1L);
        verify(fixture.locks, times(2)).unlock("job:detail:rebuild:1", "refresh-token");
        verify(fixture.cache, never()).putDetailIfGenerationUnchanged(anyLong(), any(), anyLong(), anyLong());
        verify(fixture.cache, never()).markMissing(anyLong());
    }

    @Test
    void failedBackgroundCacheWriteUnlocksAndAllowsAnotherRefresh() {
        Fixture fixture = new Fixture();
        JobVO stale = fixture.cacheStale(2L, Duration.ofMinutes(1));
        when(fixture.locks.tryLock(eq("job:detail:rebuild:2"), any(Duration.class))).thenReturn("write-token");
        when(fixture.cache.generation(2L)).thenReturn(7L);
        when(fixture.jobs.getById(2L)).thenReturn(job(2L));
        when(fixture.cache.putDetailIfGenerationUnchanged(eq(2L), any(JobVO.class), anyLong(), eq(7L)))
                .thenThrow(new IllegalStateException("cache write unavailable"));

        assertSame(stale, fixture.service.getById(2L));
        assertDoesNotThrow(() -> fixture.tasks.get(0).run());
        verify(fixture.cache).putDetailIfGenerationUnchanged(eq(2L), any(JobVO.class), anyLong(), eq(7L));
        verify(fixture.locks).unlock("job:detail:rebuild:2", "write-token");
        assertSame(stale, fixture.service.getById(2L));
        assertEquals(2, fixture.tasks.size(), "cache write failure must clear local deduplication");
        assertDoesNotThrow(() -> fixture.tasks.get(1).run());
        verify(fixture.locks, times(2)).unlock("job:detail:rebuild:2", "write-token");
    }

    @Test
    void veryStaleValueSurvivesDatabaseFailureAndOpenCircuitRejectsBeforeLockOrMapper() {
        Fixture fixture = new Fixture();
        JobVO stale = fixture.cacheStale(3L, Duration.ofHours(3));
        when(fixture.locks.tryLock(eq("job:detail:rebuild:3"), any(Duration.class))).thenReturn("rebuild-token");
        when(fixture.jobs.getById(3L)).thenThrow(new IllegalStateException("database unavailable"));

        for (int i = 0; i < 3; i++) {
            assertSame(stale, fixture.service.getById(3L));
        }
        verify(fixture.jobs, times(3)).getById(3L);
        verify(fixture.locks, times(3)).tryLock("job:detail:rebuild:3", Duration.ofSeconds(10));
        verify(fixture.locks, times(3)).unlock("job:detail:rebuild:3", "rebuild-token");
        clearInvocations(fixture.jobs, fixture.locks);

        for (int i = 0; i < 4; i++) {
            assertSame(stale, fixture.service.getById(3L));
        }
        verifyNoInteractions(fixture.jobs, fixture.locks);
        assertTrue(fixture.tasks.isEmpty(), "very stale fallback must use synchronous guard, not queue refresh");
        verify(fixture.cache, never()).putDetailIfGenerationUnchanged(anyLong(), any(), anyLong(), anyLong());
        verify(fixture.cache, never()).putDetail(anyLong(), any(), anyLong());
        verify(fixture.cache, never()).markNull(anyLong());
        verify(fixture.cache, never()).markMissing(anyLong());
    }

    @Test
    void openCircuitWithoutOldValueReturnsBusinessErrorWithoutTryingDatabaseOrLock() {
        Fixture fixture = new Fixture();
        JobVO stale = fixture.cacheStale(4L, Duration.ofHours(3));
        when(fixture.locks.tryLock(eq("job:detail:rebuild:4"), any(Duration.class))).thenReturn("token");
        when(fixture.jobs.getById(4L)).thenThrow(new IllegalStateException("database unavailable"));
        for (int i = 0; i < 3; i++) {
            assertSame(stale, fixture.service.getById(4L));
        }
        clearInvocations(fixture.jobs, fixture.locks);

        // Another job has no cached value; the same service-wide circuit protects its cold read.
        assertThrows(JobBusinessException.class, () -> fixture.service.getById(5L));
        verifyNoInteractions(fixture.jobs, fixture.locks);
        verify(fixture.cache).getCachedDetail(5L);
        verify(fixture.cache, never()).markNull(5L);
        assertTrue(fixture.tasks.isEmpty());
    }

    @Test
    void backgroundCircuitRejectionStillReleasesAcquiredRefreshLockAndClearsDeduplication() {
        Fixture fixture = new Fixture();
        JobVO stale = fixture.cacheStale(8L, Duration.ofMinutes(1));
        when(fixture.locks.tryLock(eq("job:detail:rebuild:8"), any(Duration.class))).thenReturn("refresh-token");
        when(fixture.jobs.getById(8L)).thenThrow(new IllegalStateException("database unavailable"));
        for (int i = 0; i < 4; i++) {
            assertSame(stale, fixture.service.getById(8L));
            assertEquals(i + 1, fixture.tasks.size());
            final int taskIndex = i;
            assertDoesNotThrow(() -> fixture.tasks.get(taskIndex).run());
        }
        verify(fixture.jobs, times(3)).getById(8L);
        verify(fixture.locks, times(4)).tryLock("job:detail:rebuild:8", Duration.ofSeconds(10));
        verify(fixture.locks, times(4)).unlock("job:detail:rebuild:8", "refresh-token");
        assertSame(stale, fixture.service.getById(8L));
        assertEquals(5, fixture.tasks.size(), "circuit rejection must also clear local refresh deduplication");
    }

    @Test
    void coldDatabaseFailureIsTranslatedToBusinessErrorAndReleasesRebuildLock() {
        Fixture fixture = new Fixture();
        when(fixture.locks.tryLock(eq("job:detail:rebuild:6"), any(Duration.class))).thenReturn("cold-token");
        when(fixture.jobs.getById(6L)).thenThrow(new IllegalStateException("database unavailable"));

        assertThrows(JobBusinessException.class, () -> fixture.service.getById(6L));
        verify(fixture.jobs).getById(6L);
        verify(fixture.locks).unlock("job:detail:rebuild:6", "cold-token");
        verify(fixture.cache, never()).markNull(6L);
        verify(fixture.cache, never()).markMissing(6L);
    }

    @Test
    void discardedRefreshClearsDeduplicationAndNextRequestCanEnqueueAndRun() {
        Fixture fixture = new Fixture();
        JobVO stale = fixture.cacheStale(7L, Duration.ofMinutes(1));
        when(fixture.locks.tryLock(eq("job:detail:rebuild:7"), any(Duration.class))).thenReturn("accepted-token");
        when(fixture.jobs.getById(7L)).thenReturn(job(7L));

        assertSame(stale, fixture.service.getById(7L));
        assertSame(stale, fixture.service.getById(7L));
        assertEquals(1, fixture.tasks.size(), "queued refresh must suppress duplicates");
        Runnable rejected = fixture.tasks.get(0);
        assertTrue(rejected instanceof DiscardAwareTask, "refresh must expose executor discard cleanup");
        ((DiscardAwareTask) rejected).onDiscard();
        verifyNoInteractions(fixture.jobs, fixture.locks);

        assertSame(stale, fixture.service.getById(7L));
        assertEquals(2, fixture.tasks.size(), "discard callback must make the job eligible for refresh");
        assertNotSame(rejected, fixture.tasks.get(1));
        assertSame(stale, fixture.service.getById(7L));
        assertEquals(2, fixture.tasks.size(), "replacement must retain deduplication while queued");
        assertDoesNotThrow(() -> fixture.tasks.get(1).run());
        verify(fixture.jobs).getById(7L);
        verify(fixture.cache).putDetailIfGenerationUnchanged(eq(7L), any(JobVO.class), anyLong(), eq(0L));
        verify(fixture.locks).unlock("job:detail:rebuild:7", "accepted-token");
    }

    private static Job job(long id) {
        return Job.builder().id(id).title("fresh title").companyId(9L)
                .updateTime(LocalDateTime.of(2026, 1, 1, 0, 0)).build();
    }

    private static final class Fixture {
        private final JobMapper jobs = mock(JobMapper.class);
        private final JobCacheService cache = mock(JobCacheService.class);
        private final RedisLockHelper locks = mock(RedisLockHelper.class);
        private final List<Runnable> tasks = new ArrayList<>();
        private final JobServiceImpl service = new JobServiceImpl();

        private Fixture() {
            ReflectionTestUtils.setField(service, "jobMapper", jobs);
            ReflectionTestUtils.setField(service, "companyMapper", mock(CompanyMapper.class));
            ReflectionTestUtils.setField(service, "jobCacheService", cache);
            ReflectionTestUtils.setField(service, "redisLockHelper", locks);
            ReflectionTestUtils.setField(service, "cacheRefreshExecutor", (java.util.concurrent.Executor) tasks::add);
            // Freeze the circuit clock so test execution speed cannot expire its failure window/cooldown.
            ReflectionTestUtils.setField(service, "rebuildGuard", new CacheRebuildGuard(
                    8, 3, Duration.ofSeconds(10), Duration.ofSeconds(10), () -> 0L));
        }

        private JobVO cacheStale(long id, Duration age) {
            JobVO stale = JobVO.builder().id(id).title("old title").build();
            when(cache.getCachedDetail(id)).thenReturn(new CachedJobDetail(
                    stale, System.currentTimeMillis() - age.toMillis(), 1L));
            return stale;
        }
    }
}
