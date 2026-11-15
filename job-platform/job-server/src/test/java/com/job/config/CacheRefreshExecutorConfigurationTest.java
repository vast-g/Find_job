package com.job.config;

import org.junit.jupiter.api.Test;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.*;

class CacheRefreshExecutorConfigurationTest {

    @Test
    void saturationDiscardsWithoutRunningAndNotifiesTask() throws InterruptedException {
        ThreadPoolExecutor executor = new CacheRefreshExecutorConfiguration().jobCacheRefreshExecutor();
        CountDownLatch release = new CountDownLatch(1);
        CountDownLatch started = new CountDownLatch(8);
        AtomicInteger callbacks = new AtomicInteger();
        AtomicInteger executions = new AtomicInteger();
        Runnable blocker = () -> {
            started.countDown();
            try {
                release.await();
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        };
        try {
            assertEquals(4, executor.getCorePoolSize());
            assertEquals(8, executor.getMaximumPoolSize());
            assertEquals(60, executor.getKeepAliveTime(TimeUnit.SECONDS));
            for (int i = 0; i < 208; i++) {
                executor.execute(blocker);
            }
            assertTrue(started.await(5, TimeUnit.SECONDS));
            assertEquals(200, executor.getQueue().size());
            assertDoesNotThrow(() -> executor.execute(task(callbacks, executions)));
            assertEquals(1, callbacks.get());
            assertEquals(0, executions.get());
            assertDoesNotThrow(() -> executor.execute(executions::incrementAndGet));
            assertEquals(0, executions.get());
        } finally {
            release.countDown();
            executor.shutdown();
            assertTrue(executor.awaitTermination(5, TimeUnit.SECONDS));
        }
    }

    @Test
    void shutdownRejectionAlsoNotifiesTask() throws InterruptedException {
        ThreadPoolExecutor executor = new CacheRefreshExecutorConfiguration().jobCacheRefreshExecutor();
        AtomicInteger callbacks = new AtomicInteger();
        AtomicInteger executions = new AtomicInteger();
        executor.shutdown();
        assertDoesNotThrow(() -> executor.execute(task(callbacks, executions)));
        assertEquals(1, callbacks.get());
        assertEquals(0, executions.get());
        assertTrue(executor.awaitTermination(5, TimeUnit.SECONDS));
    }

    @Test
    void acceptedTaskRunsOnNamedWorkerWithoutDiscardCallback() throws InterruptedException {
        ThreadPoolExecutor executor = new CacheRefreshExecutorConfiguration().jobCacheRefreshExecutor();
        CountDownLatch completed = new CountDownLatch(1);
        AtomicInteger callbacks = new AtomicInteger();
        java.util.concurrent.atomic.AtomicReference<String> threadName =
                new java.util.concurrent.atomic.AtomicReference<>();
        try {
            executor.execute(new CacheRefreshExecutorConfiguration.DiscardAwareTask() {
                @Override
                public void run() {
                    threadName.set(Thread.currentThread().getName());
                    completed.countDown();
                }

                @Override
                public void onDiscard() {
                    callbacks.incrementAndGet();
                }
            });
            assertTrue(completed.await(5, TimeUnit.SECONDS));
            assertTrue(threadName.get().startsWith("job-cache-refresh-"));
            assertEquals(0, callbacks.get());
        } finally {
            executor.shutdown();
            assertTrue(executor.awaitTermination(5, TimeUnit.SECONDS));
        }
    }

    private CacheRefreshExecutorConfiguration.DiscardAwareTask task(
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
}
