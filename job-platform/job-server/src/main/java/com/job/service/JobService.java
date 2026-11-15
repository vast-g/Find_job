package com.job.service;

import com.job.dto.JobDTO;
import com.job.dto.JobPageQueryDTO;
import com.job.entity.Job;
import com.job.result.PageResult;
import com.job.vo.JobVO;

import java.util.List;

public interface JobService {

    void save(JobDTO jobDTO);

    PageResult pageQuery(JobPageQueryDTO jobPageQueryDTO);

    void deleteBatch(List<Long> ids);

    JobVO getById(Long id);

    void update(JobDTO jobDTO);

    void startOrStop(Integer status, Long id);

    List<JobVO> listByCondition(Job job);
}
