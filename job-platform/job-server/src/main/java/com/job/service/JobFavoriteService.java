package com.job.service;

import com.job.vo.JobVO;

import java.util.List;

public interface JobFavoriteService {

    void add(Long jobId);

    void cancel(Long jobId);

    List<JobVO> list();
}
