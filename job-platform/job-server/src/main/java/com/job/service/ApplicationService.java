package com.job.service;

import com.job.dto.ApplicationPageQueryDTO;
import com.job.dto.ApplicationSubmitDTO;
import com.job.result.PageResult;
import com.job.vo.ApplicationVO;

import java.time.LocalDateTime;
import java.util.List;

public interface ApplicationService {

    void submit(ApplicationSubmitDTO applicationSubmitDTO);

    List<ApplicationVO> myList();

    void cancel(Long id);

    PageResult pageQuery(ApplicationPageQueryDTO applicationPageQueryDTO);

    void updateStatus(Long id, Integer status, String remark, LocalDateTime interviewTime);
}
