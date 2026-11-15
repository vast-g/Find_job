package com.job.cache;

import com.job.exception.JobBusinessException;
import java.time.Duration;
import java.util.concurrent.Semaphore;
import java.util.function.LongSupplier;
import java.util.function.Supplier;

/** Per-application bulkhead and consecutive-failure circuit for job-detail rebuilds. */
public class CacheRebuildGuard {
    private final Semaphore permits;
    private final int failureThreshold;
    private final long failureWindowNanos;
    private final long cooldownNanos;
    private final LongSupplier clock;
    private final java.util.Deque<Long> failures = new java.util.ArrayDeque<>();
    private boolean open;
    private long openedAt;
    private boolean probing;
    private long epoch;

    public CacheRebuildGuard() {
        this(8, 3, Duration.ofSeconds(10), Duration.ofSeconds(10), System::nanoTime);
    }

    public CacheRebuildGuard(int maxConcurrent, int threshold, Duration window,
                             Duration cooldown, LongSupplier nanoTime) {
        if (maxConcurrent < 1 || threshold < 1 || window.isZero() || window.isNegative()
                || cooldown.isZero() || cooldown.isNegative()) {
            throw new IllegalArgumentException("Invalid rebuild guard limits");
        }
        permits = new Semaphore(maxConcurrent);
        failureThreshold = threshold;
        failureWindowNanos = window.toNanos();
        cooldownNanos = cooldown.toNanos();
        clock = nanoTime;
    }

    public <T> T execute(Supplier<T> operation) {
        if (!permits.tryAcquire()) {
            throw new RebuildUnavailableException("岗位详情回源繁忙，请稍后重试");
        }
        try {
            long ticket = enter();
            try {
                T result = operation.get();
                succeeded(ticket);
                return result;
            } catch (JobBusinessException e) {
                succeeded(ticket);
                throw e;
            } catch (RuntimeException e) {
                failed(ticket);
                throw e;
            } catch (Error e) {
                failed(ticket);
                throw e;
            }
        } finally {
            permits.release();
        }
    }

    private synchronized long enter() {
        if (open) {
            if (probing || clock.getAsLong() - openedAt < cooldownNanos) {
                throw new RebuildUnavailableException("岗位详情暂时不可用，请稍后重试");
            }
            probing = true;
        }
        return epoch;
    }

    private synchronized void succeeded(long ticket) {
        if (ticket != epoch) return;
        failures.clear();
        if (open) {
            open = false;
            probing = false;
            epoch++;
        }
    }

    private synchronized void failed(long ticket) {
        if (ticket != epoch) return;
        long now = clock.getAsLong();
        while (!failures.isEmpty() && now - failures.peekFirst() > failureWindowNanos) {
            failures.removeFirst();
        }
        failures.addLast(now);
        if (open || failures.size() >= failureThreshold) {
            open = true;
            probing = false;
            openedAt = now;
            epoch++;
        }
    }

    public static class RebuildUnavailableException extends RuntimeException {
        public RebuildUnavailableException(String message) { super(message); }
    }
}
