package com.job.task;

import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
@Slf4j
public class MemberPushTask {

    /**
     * 每天 9 点：向会员推送新岗位
     * TODO: 接入微信订阅消息（需 access_token + 订阅消息模板）
     */
    @Scheduled(cron = "0 0 9 * * ?")
    public void pushNewJobsToMembers() {
        log.info("会员岗位推送任务执行（占位，待接入微信订阅消息）");
    }
}
