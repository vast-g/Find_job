package com.job.service.impl;

import com.github.pagehelper.Page;
import com.github.pagehelper.PageHelper;
import com.job.cache.CachedJobDetail;
import com.job.cache.CacheRebuildGuard;
import com.job.config.CacheRefreshExecutorConfiguration.DiscardAwareTask;
import com.job.constant.MessageConstant;
import com.job.constant.StatusConstant;
import com.job.dto.JobDTO;
import com.job.dto.JobPageQueryDTO;
import com.job.entity.Company;
import com.job.entity.Job;
import com.job.exception.DeletionNotAllowedException;
import com.job.exception.JobBusinessException;
import com.job.mapper.CompanyMapper;
import com.job.mapper.JobMapper;
import com.job.result.PageResult;
import com.job.service.JobCacheService;
import com.job.service.JobService;
import com.job.utils.RedisLockHelper;
import com.job.vo.JobVO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.BeanUtils;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executor;
import java.util.concurrent.RejectedExecutionException;

/**
 * 岗位服务。
 *
 * <h3>岗位详情为什么用「逻辑过期 + 异步重建」而不是「互斥锁同步重建」</h3>
 *
 * 岗位详情是典型的读多写少热点：浏览量大、管理员改得少，短暂旧值可以接受。
 * 原来的做法是缓存未命中就抢锁同步查库，其余请求等待（最多 3×50ms 后自行回源）；
 * 热点岗位重建稍慢时，等待超时的请求会一起打到数据库。
 *
 * 现在的做法：
 * <ol>
 *   <li>缓存未逻辑过期 → 直接返回</li>
 *   <li>逻辑过期 → **立即返回旧值**，同时只提交一个后台刷新任务</li>
 *   <li>缓存完全不存在（冷启动/被清） → 仍然用互斥锁同步重建</li>
 * </ol>
 *
 * 用户请求不再等待重建，数据库回源也从"一批"收敛为"一个刷新任务"。
 *
 * <p><b>代价（不隐瞒）</b>：用户可能看到短暂旧数据。因此凡是"能不能投递"这种
 * 要作数的判断，必须查数据库 —— 见 {@code ApplicationServiceImpl#submit}，
 * 它在创建投递记录前会重新校验岗位状态。
 */
@Slf4j
@Service
public class JobServiceImpl implements JobService {

    @Autowired
    private JobMapper jobMapper;
    @Autowired
    private CompanyMapper companyMapper;
    /** 批量删除时需要按 id 精确清缓存（见 deleteBatch 的说明）。 */
    @Autowired
    private JobCacheService jobCacheService;
    /** 冷启动重建时的互斥锁。 */
    @Autowired
    private RedisLockHelper redisLockHelper;
    /** 后台刷新用的有界线程池（不能在这里直接 new Thread）。 */
    @Autowired
    @Qualifier("jobCacheRefreshExecutor")
    private Executor cacheRefreshExecutor;

    /** 详情重建业务锁：同步冷启动与后台刷新共用，避免跨路径并发回源。 */
    private static final String LOCK_JOB_DETAIL_REBUILD = "job:detail:rebuild:";

    /**
     * 锁 TTL 必须覆盖"查库 + 组装 + 写缓存"的耗时。
     * 单次回源是毫秒级，10 秒足够宽裕，真出问题也能很快自愈。
     */
    private static final Duration LOCK_TTL = Duration.ofSeconds(10);

    /** 冷启动时等别人重建缓存的重试次数与间隔。 */
    private static final int WAIT_RETRIES = 3;
    private static final long WAIT_MILLIS = 50L;

    /**
     * 最大可容忍陈旧时间：逻辑过期超过这个时长就不再返回旧值，改为同步重建。
     * 避免刷新长期失败时，用户一直看到几小时前的岗位。
     */
    private static final long MAX_STALE_MILLIS = Duration.ofHours(2).toMillis();

    /**
     * 本实例内"正在排队/执行刷新"的岗位。只做单机去重，跨实例仍靠 Redis 锁。
     * 没有它的话，同一实例每秒上千次过期读会提交上千个任务把线程池队列塞满。
     */
    private final ConcurrentHashMap<Long, Boolean> refreshing = new ConcurrentHashMap<>();
    /** 同一实例所有岗位详情回源共享：最多 8 个，10 秒内连续失败 3 次熔断 10 秒。 */
    private final CacheRebuildGuard rebuildGuard = new CacheRebuildGuard();

    @Override
    public void save(JobDTO jobDTO) {
        Job job = new Job();
        BeanUtils.copyProperties(jobDTO, job);
        job.setStatus(StatusConstant.ENABLE);
        job.setViewCount(0);
        job.setApplyCount(0);
        jobMapper.insert(job);
    }

    @Override
    public PageResult pageQuery(JobPageQueryDTO jobPageQueryDTO) {
        PageHelper.startPage(jobPageQueryDTO.getPage(), jobPageQueryDTO.getPageSize());
        Page<JobVO> page = jobMapper.pageQuery(jobPageQueryDTO);
        return new PageResult(page.getTotal(), page.getResult());
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void deleteBatch(List<Long> ids) {
        for (Long id : ids) {
            Job job = jobMapper.getById(id);
            if (job != null && StatusConstant.ENABLE.equals(job.getStatus())) {
                throw new DeletionNotAllowedException(MessageConstant.JOB_ON_SHELF);
            }
            jobMapper.deleteById(id);
        }

        // ── 缓存清理（原来这里是 @CacheEvict(allEntries = true)，有两个问题）──
        //
        // 问题 1：allEntries = true 会把**整个** job:detail 缓存清空。
        //   删 3 个岗位却让 700 多个岗位的缓存全失效，之后它们被集中重新读取、
        //   在几秒内集中回填 → 反而制造了雪崩场景。改成按 id 精确清。
        //
        // 问题 2：注解是在**方法返回前**清缓存，也就是事务还没提交。
        //   这时候别的线程来读，会把"还没删掉的旧数据"重新读回缓存。
        //   所以这里注册 afterCommit，**提交之后**再清。
        final List<Long> deletedIds = new ArrayList<>(ids);
        if (TransactionSynchronizationManager.isSynchronizationActive()) {
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override
                public void afterCommit() {
                    jobCacheService.evictDetails(deletedIds);
                }
            });
        } else {
            jobCacheService.evictDetails(deletedIds);
        }
    }

    @Override
    public JobVO getById(Long id) {
        CachedJobDetail cached = jobCacheService.getCachedDetail(id);
        long now = System.currentTimeMillis();

        if (cached != null && cached.getData() != null) {
            // 1. 未逻辑过期：直接返回
            if (cached.getExpireAt() > now) {
                return cached.getData();
            }
            // 2. 逻辑过期但还在可容忍范围内：先返回旧值，后台只刷新一次
            if (now - cached.getExpireAt() <= MAX_STALE_MILLIS) {
                scheduleRefresh(id);
                return cached.getData();
            }
            // 3. 陈旧太久：不再返回，走下面的同步重建
            log.warn("岗位 {} 缓存陈旧超过 {} 小时，改为同步重建",
                    id, MAX_STALE_MILLIS / 3_600_000L);
        }

        // 空标记（防穿透）
        if (jobCacheService.isNullMarked(id)) {
            throw new JobBusinessException(MessageConstant.JOB_NOT_EXIST);
        }

        try {
            return rebuildGuard.execute(() -> loadWithLock(id));
        } catch (JobBusinessException e) {
            // 已确认岗位不存在时，不能用旧岗位伪装成仍然存在。
            throw e;
        } catch (RuntimeException e) {
            if (cached != null && cached.getData() != null) {
                // 故障期间允许超过普通陈旧上限，但不延长缓存的逻辑过期时间。
                log.warn("岗位 {} 回源失败或被熔断，返回已有旧值：{}", id, e.getMessage());
                return cached.getData();
            }
            throw new JobBusinessException("岗位详情暂时不可用，请稍后重试");
        }
    }

    /**
     * 提交一次后台刷新。
     *
     * <p>本方法**绝不抛异常、绝不阻塞**：调用方已经准备好返回旧值，
     * 刷新失败只影响新鲜度，不能连累这次请求。
     */
    private void scheduleRefresh(Long id) {
        if (refreshing.putIfAbsent(id, Boolean.TRUE) != null) {
            return; // 本实例已有任务在排队/执行，不再重复提交
        }
        try {
            cacheRefreshExecutor.execute(new DiscardAwareTask() {
                @Override
                public void run() {
                    try {
                        refresh(id);
                    } catch (Exception e) {
                        log.warn("岗位 {} 缓存后台刷新失败（保留旧值，下次再试）：{}", id, e.getMessage());
                    } finally {
                        refreshing.remove(id);
                    }
                }

                @Override
                public void onDiscard() {
                    refreshing.remove(id);
                    log.warn("岗位 {} 刷新任务被丢弃，本次仍返回旧值", id);
                }
            });
        } catch (RejectedExecutionException e) {
            refreshing.remove(id);
            log.warn("岗位 {} 刷新任务被线程池拒绝，本次仍返回旧值：{}", id, e.getMessage());
        }
    }

    /**
     * 后台刷新：抢锁 → 读库 → 重建缓存。
     *
     * <p>锁在**工作线程里**获取，而不是提交任务前获取：任务可能在队列里排队，
     * 如果请求线程先拿锁再提交，锁很可能在任务真正执行前就过期了。
     */
    private void refresh(Long id) {
        String lockKey = LOCK_JOB_DETAIL_REBUILD + id;
        String token = redisLockHelper.tryLock(lockKey, LOCK_TTL);
        if (token == null) {
            return; // 别的实例/线程正在刷新
        }
        try {
            // 双重检查必须在熔断守卫之前：跳过刷新不应被计为一次成功回源。
            CachedJobDetail latest = jobCacheService.getCachedDetail(id);
            if (latest != null && latest.getData() != null
                    && latest.getExpireAt() > System.currentTimeMillis()) {
                return;
            }
            // 后台任务排队期间岗位可能已被确认删除，避免再次查库。
            if (jobCacheService.isNullMarked(id)) {
                return;
            }
            rebuildGuard.execute(() -> {
                long generation = jobCacheService.generation(id);
                Job job = jobMapper.getById(id);
                if (job == null) {
                    jobCacheService.markMissing(id);
                    return null;
                }
                JobVO vo = buildVO(job);
                jobCacheService.putDetailIfGenerationUnchanged(id, vo, versionOf(job), generation);
                return null;
            });
        } finally {
            redisLockHelper.unlock(lockKey, token);
        }
    }

    /**
     * 冷启动/陈旧过久的同步重建（原有互斥锁路径，保留）。
     *
     * <p>这时没有任何旧值可返回，因此请求需要等待；抢不到锁的请求短暂等待后
     * 降级查库，保证请求能返回。
     */
    private JobVO loadWithLock(Long id) {
        String lockKey = LOCK_JOB_DETAIL_REBUILD + id;
        String token = redisLockHelper.tryLock(lockKey, LOCK_TTL);

        if (token == null) {
            for (int i = 0; i < WAIT_RETRIES; i++) {
                sleepQuietly(WAIT_MILLIS);
                CachedJobDetail again = jobCacheService.getCachedDetail(id);
                if (again != null && again.getData() != null
                        && again.getExpireAt() > System.currentTimeMillis()) {
                    return again.getData();
                }
                if (jobCacheService.isNullMarked(id)) {
                    throw new JobBusinessException(MessageConstant.JOB_NOT_EXIST);
                }
            }
            return loadFromDb(id);
        }

        try {
            // 双重检查：从"发现未命中"到"抢到锁"之间，别人可能已经重建完了。
            // 注意只接受**未逻辑过期**的值 —— 陈旧值正是我们要重建的对象，
            // 直接返回它会让"陈旧过久"的分支永远刷不新。
            CachedJobDetail again = jobCacheService.getCachedDetail(id);
            if (again != null && again.getData() != null
                    && again.getExpireAt() > System.currentTimeMillis()) {
                return again.getData();
            }
            // 也要再看一眼空标记：别人可能刚确认这个岗位不存在
            if (jobCacheService.isNullMarked(id)) {
                throw new JobBusinessException(MessageConstant.JOB_NOT_EXIST);
            }

            long generation = jobCacheService.generation(id);
            Job job = jobMapper.getById(id);
            if (job == null) {
                jobCacheService.markNull(id);
                throw new JobBusinessException(MessageConstant.JOB_NOT_EXIST);
            }
            JobVO vo = buildVO(job);
            jobCacheService.putDetailIfGenerationUnchanged(id, vo, versionOf(job), generation);
            return vo;
        } finally {
            // 中途抛异常（比如岗位不存在）也要把锁放掉，否则只能等 TTL 自然过期
            redisLockHelper.unlock(lockKey, token);
        }
    }

    /** 直接回源组装 VO，不读写缓存（给"降级"路径用）。 */
    private JobVO loadFromDb(Long id) {
        Job job = jobMapper.getById(id);
        if (job == null) {
            throw new JobBusinessException(MessageConstant.JOB_NOT_EXIST);
        }
        return buildVO(job);
    }

    /** 把 Job 组装成对外的 JobVO（补上企业名）。 */
    private JobVO buildVO(Job job) {
        JobVO jobVO = new JobVO();
        BeanUtils.copyProperties(job, jobVO);
        Company company = companyMapper.getById(job.getCompanyId());
        if (company != null) {
            jobVO.setCompanyName(company.getName());
        }
        return jobVO;
    }

    /** 数据版本：优先用 updateTime，没有则退回 0（老数据）。 */
    private long versionOf(Job job) {
        LocalDateTime updateTime = job.getUpdateTime();
        return updateTime == null ? 0L : updateTime.atZone(java.time.ZoneId.systemDefault()).toInstant().toEpochMilli();
    }

    /** 短暂休眠，用于"等别人重建缓存"；被中断就恢复中断标记并提前返回。 */
    private void sleepQuietly(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    @Override
    public void update(JobDTO jobDTO) {
        Job job = new Job();
        BeanUtils.copyProperties(jobDTO, job);
        jobMapper.update(job);
        // 先写库、再清缓存；同时推进刷新代际，挡掉正在执行的慢刷新
        jobCacheService.evictDetail(jobDTO.getId());
    }

    @Override
    public void startOrStop(Integer status, Long id) {
        if (StatusConstant.ENABLE.equals(status)) {
            Job job = jobMapper.getById(id);
            Company company = companyMapper.getById(job.getCompanyId());
            if (company == null || StatusConstant.DISABLE.equals(company.getStatus())) {
                throw new JobBusinessException(MessageConstant.COMPANY_DISABLED);
            }
        }
        Job job = Job.builder().id(id).status(status).build();
        jobMapper.update(job);
        jobCacheService.evictDetail(id);
    }

    @Override
    public List<JobVO> listByCondition(Job job) {
        return jobMapper.listByCondition(job);
    }
}
