package com.job.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

@Configuration
public class CacheRefreshExecutorConfiguration {

    /** Tasks use this callback to release local deduplication when rejected. */
    public interface DiscardAwareTask extends Runnable {
        void onDiscard();
    }

    public static class DiscardAwarePolicy extends ThreadPoolExecutor.DiscardPolicy {
        @Override
        public void rejectedExecution(Runnable task, ThreadPoolExecutor executor) {
            super.rejectedExecution(task, executor);
            if (task instanceof DiscardAwareTask) {
                ((DiscardAwareTask) task).onDiscard();
            }
        }
    }

    @Bean(name = "jobCacheRefreshExecutor", destroyMethod = "shutdown")
    public ThreadPoolExecutor jobCacheRefreshExecutor() {
        AtomicInteger threadSequence = new AtomicInteger();
        ThreadFactory threadFactory = task ->
                new Thread(task, "job-cache-refresh-" + threadSequence.incrementAndGet());
        return new ThreadPoolExecutor(4, 8, 60, TimeUnit.SECONDS,
                new ArrayBlockingQueue<>(200), threadFactory, new DiscardAwarePolicy());
    }
}
