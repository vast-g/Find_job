package com.job.service.impl;

import com.job.context.BaseContext;
import com.job.entity.JobFavorite;
import com.job.mapper.JobFavoriteMapper;
import com.job.service.JobFavoriteService;
import com.job.vo.JobVO;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.List;

@Service
public class JobFavoriteServiceImpl implements JobFavoriteService {

    @Autowired
    private JobFavoriteMapper jobFavoriteMapper;

    @Override
    public void add(Long jobId) {
        Long userId = BaseContext.getCurrentId();
        if (jobFavoriteMapper.count(userId, jobId) == 0) {
            JobFavorite favorite = JobFavorite.builder()
                    .userId(userId)
                    .jobId(jobId)
                    .createTime(LocalDateTime.now())
                    .build();
            jobFavoriteMapper.insert(favorite);
        }
    }

    @Override
    public void cancel(Long jobId) {
        jobFavoriteMapper.delete(BaseContext.getCurrentId(), jobId);
    }

    @Override
    public List<JobVO> list() {
        return jobFavoriteMapper.listByUserId(BaseContext.getCurrentId());
    }
}
