package com.job.task;

import com.job.mapper.JobMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;

/**
 * 定时扫描已过截止时间的在招岗位，改为已结束
 */
@Component
@Slf4j
public class JobDeadlineTask {

    @Autowired
    private JobMapper jobMapper;

    @Scheduled(cron = "0 0 2 * * ?")
    public void updateDeadlineJobs() {
        log.info("开始扫描过期岗位...");
        jobMapper.updateStatusEnded(LocalDateTime.now());
    }
}
