package com.job.service;

import com.job.dto.JobCategoryDTO;
import com.job.entity.JobCategory;
import com.job.result.PageResult;

import java.util.List;

public interface JobCategoryService {

    void save(JobCategoryDTO jobCategoryDTO);

    PageResult pageQuery(JobCategoryDTO jobCategoryDTO);

    void deleteById(Long id);

    JobCategory getById(Long id);

    void update(JobCategoryDTO jobCategoryDTO);

    List<JobCategory> list();

    void startOrStop(Integer status, Long id);
}
