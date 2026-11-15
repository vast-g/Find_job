package com.job.service.impl;

import com.github.pagehelper.Page;
import com.github.pagehelper.PageHelper;
import com.job.constant.MessageConstant;
import com.job.constant.StatusConstant;
import com.job.dto.JobCategoryDTO;
import com.job.entity.JobCategory;
import com.job.exception.DeletionNotAllowedException;
import com.job.mapper.JobCategoryMapper;
import com.job.mapper.JobMapper;
import com.job.result.PageResult;
import com.job.service.JobCategoryService;
import com.job.utils.RedisLockHelper;
import lombok.Data;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.BeanUtils;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.cache.Cache;
import org.springframework.cache.CacheManager;
import org.springframework.cache.annotation.CacheEvict;
import org.springframework.stereotype.Service;

import java.io.Serializable;
import java.time.Duration;
import java.time.LocalDateTime;
import java.util.List;
import java.util.concurrent.CompletableFuture;

/**
 * 岗位分类。
 *
 * <h3>为什么分类列表用「逻辑过期」而不是加锁重建</h3>
 *
 * 分类只有 8 条、几乎不变，但**首页每次打开都要读**，是典型的高频热点。
 * 两种防击穿方案在这里的差别是：
 *
 * <ul>
 *   <li><b>互斥锁</b>（{@code job:detail} 用的那种）：未命中时只放一个线程回源，
 *       其余线程**等待**。适合"必须拿到最新值"的场景（岗位详情），
 *       代价是并发时有人要等。</li>
 *   <li><b>逻辑过期</b>（本类）：缓存**永不物理过期**，只在值里记一个
 *       "逻辑过期时间"。读到已过期时，**立刻返回旧值**，同时异步重建。
 *       适合"能容忍短暂旧值、但要求高吞吐"的场景（分类列表）。</li>
 * </ul>
 *
 * <p>一句话取舍：**岗位详情不能给用户看旧数据，分类列表可以。**
 *
 * <h3>逻辑过期的代价（必须知道）</h3>
 * 因为缓存不物理过期，一旦**绕过应用**改了库（比如直接跑 SQL），
 * 缓存就不会自己消失 —— 所以这里还留了一个 30 分钟的逻辑过期兜底，
 * 保证最坏情况下 30 分钟内也会被异步刷新一次。
 * 走应用内改分类（save/update/delete/startOrStop）时，
 * 下面那些 {@code @CacheEvict} 会直接把这个缓存删掉，下一读就是新数据。
 */
@Slf4j
@Service
public class JobCategoryServiceImpl implements JobCategoryService {

    /** 缓存名，与 {@code @CacheEvict(cacheNames = "category:list")} 一致。 */
    private static final String CACHE_CATEGORY_LIST = "category:list";

    /** 缓存键。用的是"整个列表"这一条记录，所以固定一个 key 即可。 */
    private static final String KEY_CATEGORY_LIST = "all";

    /** 逻辑过期时间：即使没人改，30 分钟后也会异步刷新一次（兜底）。 */
    private static final Duration LOGICAL_TTL = Duration.ofMinutes(30);

    /** 重建锁：保证同一时刻只有一个线程去做异步重建。 */
    private static final String LOCK_CATEGORY_REBUILD = "category:rebuild";

    /** 重建锁 TTL：一次查库是毫秒级，10 秒足够。 */
    private static final Duration LOCK_TTL = Duration.ofSeconds(10);

    @Autowired
    private JobCategoryMapper jobCategoryMapper;
    @Autowired
    private JobMapper jobMapper;
    @Autowired
    private CacheManager cacheManager;
    @Autowired
    private RedisLockHelper redisLockHelper;

    @Override
    @CacheEvict(cacheNames = CACHE_CATEGORY_LIST, allEntries = true)
    public void save(JobCategoryDTO jobCategoryDTO) {
        JobCategory jobCategory = new JobCategory();
        BeanUtils.copyProperties(jobCategoryDTO, jobCategory);
        jobCategory.setStatus(StatusConstant.ENABLE);
        jobCategory.setCreateTime(LocalDateTime.now());
        jobCategory.setUpdateTime(LocalDateTime.now());
        jobCategoryMapper.insert(jobCategory);
    }

    @Override
    public PageResult pageQuery(JobCategoryDTO jobCategoryDTO) {
        PageHelper.startPage(jobCategoryDTO.getPage(), jobCategoryDTO.getPageSize());
        Page<JobCategory> page = jobCategoryMapper.pageQuery(jobCategoryDTO);
        return new PageResult(page.getTotal(), page.getResult());
    }

    @Override
    @CacheEvict(cacheNames = CACHE_CATEGORY_LIST, allEntries = true)
    public void deleteById(Long id) {
        Integer count = jobMapper.countByCategoryId(id);
        if (count != null && count > 0) {
            throw new DeletionNotAllowedException(MessageConstant.CATEGORY_BE_RELATED_BY_JOB);
        }
        jobCategoryMapper.deleteById(id);
    }

    @Override
    public JobCategory getById(Long id) {
        return jobCategoryMapper.getById(id);
    }

    @Override
    @CacheEvict(cacheNames = CACHE_CATEGORY_LIST, allEntries = true)
    public void update(JobCategoryDTO jobCategoryDTO) {
        JobCategory jobCategory = new JobCategory();
        BeanUtils.copyProperties(jobCategoryDTO, jobCategory);
        jobCategory.setUpdateTime(LocalDateTime.now());
        jobCategoryMapper.update(jobCategory);
    }

    /**
     * 分类列表（逻辑过期 + 异步重建）。
     *
     * <p>注意这里**换掉了原来的 {@code @Cacheable}**：{@code @Cacheable} 只能做
     * "物理 TTL"，没法表达"过期了也照样返回旧值、后台再刷新"。
     * 所以改成手动读写缓存，但 cache 名和 key 仍走同一个 {@link CacheManager}，
     * 这样上面那几个 {@code @CacheEvict} 依然能把它清掉，不用改注解。
     */
    @Override
    public List<JobCategory> list() {
        Cache cache = cacheManager.getCache(CACHE_CATEGORY_LIST);
        if (cache == null) {
            // 缓存组件不可用：直接查库，保证功能不挂
            return jobCategoryMapper.listEnabled();
        }

        CachedList cached = readCache(cache);
        long now = System.currentTimeMillis();

        // 情况 1：根本没有缓存（首次访问 / 刚被 @CacheEvict 清掉）→ 同步加载
        if (cached == null) {
            return loadAndCache(cache);
        }

        // 情况 2：逻辑未过期 → 直接返回
        if (cached.getExpireAt() > now) {
            return cached.getData();
        }

        // 情况 3：逻辑已过期 → **先返回旧值**，再异步重建
        //
        // 关键点：抢不到锁也照样返回旧值。因为"返回旧值"本来就是这套方案的设计目的 ——
        // 有人在重建就够了，其他人不需要等，也不会重复重建。
        String token = redisLockHelper.tryLock(LOCK_CATEGORY_REBUILD, LOCK_TTL);
        if (token != null) {
            // 用独立线程重建，不阻塞当前请求
            CompletableFuture.runAsync(() -> {
                try {
                    List<JobCategory> fresh = jobCategoryMapper.listEnabled();
                    cache.put(KEY_CATEGORY_LIST, new CachedList(fresh,
                            System.currentTimeMillis() + LOGICAL_TTL.toMillis()));
                    log.info("分类缓存异步重建完成，共 {} 条", fresh == null ? 0 : fresh.size());
                } catch (Exception e) {
                    // 重建失败不影响本次返回（已经给了旧值），下一读会再试
                    log.warn("分类缓存异步重建失败：{}", e.getMessage());
                } finally {
                    redisLockHelper.unlock(LOCK_CATEGORY_REBUILD, token);
                }
            });
        }
        return cached.getData();
    }

    /** 同步加载并写入缓存（首次访问的路径）。 */
    private List<JobCategory> loadAndCache(Cache cache) {
        List<JobCategory> list = jobCategoryMapper.listEnabled();
        try {
            cache.put(KEY_CATEGORY_LIST, new CachedList(list,
                    System.currentTimeMillis() + LOGICAL_TTL.toMillis()));
        } catch (Exception e) {
            // 写缓存失败不影响本次返回
            log.warn("写入分类缓存失败：{}", e.getMessage());
        }
        return list;
    }

    /** 读缓存；旧格式（不是 CachedList）或反序列化失败一律当未命中。 */
    private CachedList readCache(Cache cache) {
        try {
            Cache.ValueWrapper wrapper = cache.get(KEY_CATEGORY_LIST);
            if (wrapper == null) {
                return null;
            }
            Object value = wrapper.get();
            return (value instanceof CachedList) ? (CachedList) value : null;
        } catch (Exception e) {
            log.warn("读取分类缓存失败（按未命中处理）：{}", e.getMessage());
            return null;
        }
    }

    @Override
    @CacheEvict(cacheNames = CACHE_CATEGORY_LIST, allEntries = true)
    public void startOrStop(Integer status, Long id) {
        JobCategory jobCategory = JobCategory.builder().id(id).status(status).build();
        jobCategory.setUpdateTime(LocalDateTime.now());
        jobCategoryMapper.update(jobCategory);
    }

    /**
     * 逻辑过期缓存的包装：把"数据"和"逻辑过期时间戳"一起存。
     *
     * <p>为什么不能只存数据：逻辑过期方案依赖"值里自带的过期时间"来判断新鲜度，
     * 而 Redis 的物理 TTL 是不设的（否则到期就真没了，没旧值可返回）。
     *
     * <p>用 {@code @Data} 生成 getter/setter，Jackson 序列化需要它们。
     */
    @Data
    public static class CachedList implements Serializable {
        private static final long serialVersionUID = 1L;

        /** 分类列表本体。 */
        private List<JobCategory> data;

        /** 逻辑过期时间（epoch 毫秒）。 */
        private long expireAt;

        public CachedList() {
        }

        public CachedList(List<JobCategory> data, long expireAt) {
            this.data = data;
            this.expireAt = expireAt;
        }
    }
}
