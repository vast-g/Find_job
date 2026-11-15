package com.job.service.impl;

import com.github.pagehelper.Page;
import com.github.pagehelper.PageHelper;
import com.job.constant.MessageConstant;
import com.job.constant.StatusConstant;
import com.job.context.BaseContext;
import com.job.dto.ApplicationPageQueryDTO;
import com.job.dto.ApplicationSubmitDTO;
import com.job.entity.Application;
import com.job.entity.Job;
import com.job.entity.Resume;
import com.job.exception.ApplicationBusinessException;
import com.job.mapper.ApplicationMapper;
import com.job.mapper.JobMapper;
import com.job.mapper.ResumeMapper;
import com.job.result.PageResult;
import com.job.service.ApplicationService;
import com.job.vo.ApplicationVO;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;

@Service
public class ApplicationServiceImpl implements ApplicationService {

    @Autowired
    private ApplicationMapper applicationMapper;
    @Autowired
    private JobMapper jobMapper;
    @Autowired
    private ResumeMapper resumeMapper;

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void submit(ApplicationSubmitDTO applicationSubmitDTO) {
        Long userId = BaseContext.getCurrentId();
        Long jobId = applicationSubmitDTO.getJobId();
        Long resumeId = applicationSubmitDTO.getResumeId();

        // 1. 重复投递校验
        if (applicationMapper.count(userId, jobId) > 0) {
            throw new ApplicationBusinessException(MessageConstant.APPLICATION_REPEAT);
        }
        // 2. 岗位在招校验
        Job job = jobMapper.getById(jobId);
        if (job == null || !StatusConstant.ENABLE.equals(job.getStatus())) {
            throw new ApplicationBusinessException(MessageConstant.JOB_ENDED);
        }
        // 3. 简历存在校验
        Resume resume = resumeMapper.getById(resumeId);
        if (resume == null) {
            throw new ApplicationBusinessException(MessageConstant.RESUME_NOT_FOUND);
        }

        // 4. 插入投递记录
        Application application = Application.builder()
                .userId(userId)
                .jobId(jobId)
                .resumeId(resumeId)
                .status(1)
                .createTime(LocalDateTime.now())
                .updateTime(LocalDateTime.now())
                .build();
        applicationMapper.insert(application);

        // 5. 岗位投递数 + 1
        jobMapper.incrementApplyCount(jobId);
    }

    @Override
    public List<ApplicationVO> myList() {
        return applicationMapper.listByUserId(BaseContext.getCurrentId());
    }

    @Override
    public void cancel(Long id) {
        Application application = applicationMapper.getById(id);
        if (application != null && application.getStatus() == 1) {
            Application update = new Application();
            update.setId(id);
            update.setStatus(5);
            update.setUpdateTime(LocalDateTime.now());
            applicationMapper.update(update);
        }
    }

    @Override
    public PageResult pageQuery(ApplicationPageQueryDTO applicationPageQueryDTO) {
        PageHelper.startPage(applicationPageQueryDTO.getPage(), applicationPageQueryDTO.getPageSize());
        Page<ApplicationVO> page = applicationMapper.pageQuery(applicationPageQueryDTO);
        return new PageResult(page.getTotal(), page.getResult());
    }

    @Override
    public void updateStatus(Long id, Integer status, String remark, LocalDateTime interviewTime) {
        Application update = new Application();
        update.setId(id);
        update.setStatus(status);
        update.setRemark(remark);
        update.setInterviewTime(interviewTime);
        update.setUpdateTime(LocalDateTime.now());
        applicationMapper.update(update);
    }
}
