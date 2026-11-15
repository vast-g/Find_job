package com.job.cache;

import com.job.config.CacheRefreshExecutorConfiguration;
import com.job.exception.JobBusinessException;
import org.junit.jupiter.api.Test;

import java.time.Duration;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import java.util.function.LongSupplier;

import static org.junit.jupiter.api.Assertions.*;

class CacheResilienceTest {
    private static final Duration WINDOW = Duration.ofSeconds(10);
    private static final Duration COOLDOWN = Duration.ofSeconds(10);

    @Test
    void opensAtFailureThresholdAndRejectsWithoutInvokingSupplierUntilCooldown() {
        TestClock clock = new TestClock();
        CacheRebuildGuard guard = guard(2, 3, clock);
        fail(guard);
        fail(guard);
        fail(guard);
        assertUnavailable(guard);
        clock.advance(COOLDOWN.minusNanos(1));
        assertUnavailable(guard);
        clock.advance(Duration.ofNanos(1));
        assertEquals("recovered", guard.execute(() -> "recovered"));
        assertEquals("closed", guard.execute(() -> "closed"));
    }

    @Test
    void failuresOutsideWindowDoNotAccumulateTowardThreshold() {
        TestClock clock = new TestClock();
        CacheRebuildGuard guard = guard(1, 3, clock);
        fail(guard);
        fail(guard);
        clock.advance(WINDOW.plusNanos(1));
        fail(guard);
        // A fourth infrastructure failure is still admitted: only two belong to the new window.
        fail(guard);
        fail(guard);
        assertUnavailable(guard);
    }

    @Test
    void slidingWindowMeasuresAllFailuresRatherThanOnlyLastFailureGap() {
        TestClock clock = new TestClock();
        CacheRebuildGuard guard = guard(1, 3, clock);
        fail(guard);
        clock.advance(Duration.ofSeconds(9));
        fail(guard);
        clock.advance(Duration.ofSeconds(9));
        fail(guard); // first failure has expired even though each gap is under 10s
        assertEquals("healthy", guard.execute(() -> "healthy"));
    }

    @Test
    void successfulResultResetsConsecutiveFailureCountAndPreservesNullResults() {
        CacheRebuildGuard guard = guard(1, 3, new TestClock());
        fail(guard);
        fail(guard);
        assertNull(guard.execute(() -> null));
        fail(guard);
        fail(guard);
        assertEquals("healthy", guard.execute(() -> "healthy"));
    }

    @Test
    void businessExceptionIsPropagatedAndResetsInfrastructureFailures() {
        CacheRebuildGuard guard = guard(1, 3, new TestClock());
        fail(guard);
        fail(guard);
        JobBusinessException missing = new JobBusinessException("job not found");
        assertSame(missing, assertThrows(JobBusinessException.class,
                () -> guard.execute(() -> { throw missing; })));
        fail(guard);
        fail(guard);
        assertEquals("still healthy", guard.execute(() -> "still healthy"));
    }

    @Test
    void failedHalfOpenProbeReopensForFullCooldownAndSuccessfulProbeResetsFailures() {
        TestClock clock = new TestClock();
        CacheRebuildGuard guard = guard(1, 3, clock);
        fail(guard);
        fail(guard);
        fail(guard);
        clock.advance(COOLDOWN);
        fail(guard);
        assertUnavailable(guard);
        clock.advance(COOLDOWN.minusNanos(1));
        assertUnavailable(guard);
        clock.advance(Duration.ofNanos(1));
        assertEquals("probe success", guard.execute(() -> "probe success"));
        fail(guard);
        fail(guard);
        assertEquals("not tripped by old failures", guard.execute(() -> "not tripped by old failures"));
    }

    @Test
    void businessOutcomeDuringHalfOpenClosesCircuit() {
        TestClock clock = new TestClock();
        CacheRebuildGuard guard = guard(1, 1, clock);
        fail(guard);
        clock.advance(COOLDOWN);
        JobBusinessException missing = new JobBusinessException("job not found");
        assertSame(missing, assertThrows(JobBusinessException.class,
                () -> guard.execute(() -> { throw missing; })));
        assertEquals("closed", guard.execute(() -> "closed"));
    }

    @Test
    void onlyOneHalfOpenProbeRunsEvenWithSpareBulkheadCapacity() throws Exception {
        TestClock clock = new TestClock();
        CacheRebuildGuard guard = guard(2, 1, clock);
        fail(guard);
        clock.advance(COOLDOWN);
        CountDownLatch entered = new CountDownLatch(1);
        CountDownLatch release = new CountDownLatch(1);
        ExecutorService worker = Executors.newSingleThreadExecutor();
        try {
            Future<String> probe = worker.submit(() -> guard.execute(() -> {
                entered.countDown();
                await(release);
                return "probe";
            }));
            assertTrue(entered.await(5, TimeUnit.SECONDS), "probe did not start");
            assertUnavailable(guard);
            // Another elapsed cooldown must not permit an overlapping probe.
            clock.advance(COOLDOWN);
            assertUnavailable(guard);
            release.countDown();
            assertEquals("probe", probe.get(5, TimeUnit.SECONDS));
            assertEquals("closed", guard.execute(() -> "closed"));
        } finally {
            release.countDown();
            stop(worker);
        }
    }

    @Test
    void completionStartedBeforeTripCannotCloseLaterOpenCircuit() throws Exception {
        TestClock clock = new TestClock();
        CacheRebuildGuard guard = guard(2, 1, clock);
        CountDownLatch entered = new CountDownLatch(1);
        CountDownLatch release = new CountDownLatch(1);
        ExecutorService worker = Executors.newSingleThreadExecutor();
        try {
            Future<String> oldRequest = worker.submit(() -> guard.execute(() -> {
                entered.countDown();
                await(release);
                return "old success";
            }));
            assertTrue(entered.await(5, TimeUnit.SECONDS), "old request did not start");
            fail(guard);
            release.countDown();
            assertEquals("old success", oldRequest.get(5, TimeUnit.SECONDS));
            assertUnavailable(guard);
            clock.advance(COOLDOWN.minusNanos(1));
            assertUnavailable(guard);
            clock.advance(Duration.ofNanos(1));
            assertEquals("new probe", guard.execute(() -> "new probe"));
        } finally {
            release.countDown();
            stop(worker);
        }
    }

    @Test
    void bulkheadRejectsWithoutRunningSupplierAndReleasesPermitAfterSuccessAndFailure() throws Exception {
        CacheRebuildGuard guard = guard(1, 3, new TestClock());
        CountDownLatch entered = new CountDownLatch(1);
        CountDownLatch release = new CountDownLatch(1);
        ExecutorService worker = Executors.newSingleThreadExecutor();
        try {
            Future<String> active = worker.submit(() -> guard.execute(() -> {
                entered.countDown();
                await(release);
                return "active";
            }));
            assertTrue(entered.await(5, TimeUnit.SECONDS), "active request did not start");
            // Rejections must neither invoke work nor count as infrastructure failures.
            for (int i = 0; i < 4; i++) {
                assertUnavailable(guard);
            }
            release.countDown();
            assertEquals("active", active.get(5, TimeUnit.SECONDS));
            fail(guard);
            assertEquals("permit released", guard.execute(() -> "permit released"));
        } finally {
            release.countDown();
            stop(worker);
        }
    }

    @Test
    void defaultGuardTripsAfterThreeInfrastructureFailures() {
        CacheRebuildGuard guard = new CacheRebuildGuard();
        fail(guard);
        fail(guard);
        fail(guard);
        assertUnavailable(guard);
    }

    @Test
    void saturatedBoundedExecutorNotifiesDiscardedTaskWithoutRunningIt() throws Exception {
        ThreadPoolExecutor executor = boundedExecutor();
        CountDownLatch entered = new CountDownLatch(1);
        CountDownLatch release = new CountDownLatch(1);
        CountDownLatch queuedRan = new CountDownLatch(1);
        AtomicInteger callbacks = new AtomicInteger();
        AtomicInteger rejectedExecutions = new AtomicInteger();
        try {
            executor.execute(() -> {
                entered.countDown();
                await(release);
            });
            assertTrue(entered.await(5, TimeUnit.SECONDS), "worker did not start");
            executor.execute(queuedRan::countDown);
            assertEquals(1, executor.getQueue().size());
            assertDoesNotThrow(() -> executor.execute(discardAware(callbacks, rejectedExecutions)));
            assertEquals(1, callbacks.get());
            assertEquals(0, rejectedExecutions.get());
            assertDoesNotThrow(() -> executor.execute(rejectedExecutions::incrementAndGet));
            assertEquals(0, rejectedExecutions.get());
            release.countDown();
            assertTrue(queuedRan.await(5, TimeUnit.SECONDS), "accepted queued work was lost");
        } finally {
            release.countDown();
            stop(executor);
        }
        assertEquals(1, callbacks.get());
        assertEquals(0, rejectedExecutions.get());
    }

    @Test
    void shutdownExecutorNotifiesDiscardedTaskExactlyOnceWithoutRunningIt() throws Exception {
        ThreadPoolExecutor executor = boundedExecutor();
        AtomicInteger callbacks = new AtomicInteger();
        AtomicInteger executions = new AtomicInteger();
        try {
            executor.shutdown();
            assertDoesNotThrow(() -> executor.execute(discardAware(callbacks, executions)));
            assertEquals(1, callbacks.get());
            assertEquals(0, executions.get());
            assertDoesNotThrow(() -> executor.execute(executions::incrementAndGet));
            assertEquals(0, executions.get());
        } finally {
            stop(executor);
        }
    }

    private static CacheRebuildGuard guard(int maxConcurrent, int threshold, TestClock clock) {
        return new CacheRebuildGuard(maxConcurrent, threshold, WINDOW, COOLDOWN, clock);
    }

    private static void fail(CacheRebuildGuard guard) {
        IllegalStateException failure = new IllegalStateException("database unavailable");
        assertSame(failure, assertThrows(IllegalStateException.class,
                () -> guard.execute(() -> { throw failure; })));
    }

    private static void assertUnavailable(CacheRebuildGuard guard) {
        AtomicInteger invocations = new AtomicInteger();
        assertThrows(CacheRebuildGuard.RebuildUnavailableException.class,
                () -> guard.execute(invocations::incrementAndGet));
        assertEquals(0, invocations.get(), "rejected rebuild must not invoke its supplier");
    }

    private static ThreadPoolExecutor boundedExecutor() {
        return new ThreadPoolExecutor(1, 1, 0, TimeUnit.SECONDS,
                new ArrayBlockingQueue<>(1), new CacheRefreshExecutorConfiguration.DiscardAwarePolicy());
    }

    private static CacheRefreshExecutorConfiguration.DiscardAwareTask discardAware(
            AtomicInteger callbacks, AtomicInteger executions) {
        return new CacheRefreshExecutorConfiguration.DiscardAwareTask() {
            @Override
            public void run() {
                executions.incrementAndGet();
            }

            @Override
            public void onDiscard() {
                callbacks.incrementAndGet();
            }
        };
    }

    private static void await(CountDownLatch latch) {
        try {
            if (!latch.await(5, TimeUnit.SECONDS)) {
                throw new AssertionError("timed out waiting for test release");
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new AssertionError("test worker interrupted", e);
        }
    }

    private static void stop(ExecutorService executor) throws InterruptedException {
        executor.shutdownNow();
        assertTrue(executor.awaitTermination(5, TimeUnit.SECONDS), "test executor did not terminate");
    }

    private static final class TestClock implements LongSupplier {
        // Zero also covers implementations that accidentally use zero as an unset timestamp.
        private final AtomicLong nanos = new AtomicLong();

        @Override
        public long getAsLong() {
            return nanos.get();
        }

        private void advance(Duration duration) {
            nanos.addAndGet(duration.toNanos());
        }
    }
}
