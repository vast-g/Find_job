package com.job.entity;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.io.Serializable;
import java.time.LocalDateTime;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class Application implements Serializable {

    private static final long serialVersionUID = 1L;

    private Long id;
    private Long userId;
    private Long jobId;
    private Long resumeId;
    //1已投递 2已查看 3面试邀请 4已录用 5已拒绝
    private Integer status;
    private LocalDateTime interviewTime;
    private String remark;
    private LocalDateTime createTime;
    private LocalDateTime updateTime;
}
