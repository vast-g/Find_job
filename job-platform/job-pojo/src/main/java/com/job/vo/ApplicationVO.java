package com.job.vo;

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
public class ApplicationVO implements Serializable {

    private Long id;
    private Long userId;
    private String userName;
    private Long jobId;
    private String jobTitle;
    private Long companyId;
    private String companyName;
    private Long resumeId;
    private String resumeName;
    private Integer status;
    private LocalDateTime interviewTime;
    private String remark;
    private LocalDateTime createTime;
}
