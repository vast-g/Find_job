package com.job.cache;

import com.job.vo.JobVO;

import java.io.Serializable;

/**
 * 岗位详情缓存的信封：数据本体 + 业务过期时间。
 *
 * <p>逻辑过期方案要求 Redis 里**一直留着旧值**（物理上不删），
 * 靠这里自带的 {@code expireAt} 判断新鲜度。这样即使刷新慢了，
 * 请求仍然能拿到旧数据快速返回，而不是全部打到数据库。
 */
public class CachedJobDetail implements Serializable {

    private static final long serialVersionUID = 1L;

    /** 岗位详情本体。 */
    private JobVO data;

    /** 逻辑过期时间（epoch 毫秒）。超过它就算"陈旧但仍可用"。 */
    private long expireAt;

    /** 数据版本（取岗位 updateTime 毫秒），用于防止慢刷新用旧数据覆盖新数据。 */
    private long version;

    public CachedJobDetail() {
    }

    public CachedJobDetail(JobVO data, long expireAt, long version) {
        this.data = data;
        this.expireAt = expireAt;
        this.version = version;
    }

    public JobVO getData() {
        return data;
    }

    public void setData(JobVO data) {
        this.data = data;
    }

    public long getExpireAt() {
        return expireAt;
    }

    public void setExpireAt(long expireAt) {
        this.expireAt = expireAt;
    }

    public long getVersion() {
        return version;
    }

    public void setVersion(long version) {
        this.version = version;
    }
}
