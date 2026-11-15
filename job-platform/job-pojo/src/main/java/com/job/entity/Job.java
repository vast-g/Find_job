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
public class Job implements Serializable {

    private static final long serialVersionUID = 1L;

    private Long id;
    private Long companyId;
    private Long categoryId;
    private String title;
    private String description;
    private String requirement;
    private Integer salaryMin;
    private Integer salaryMax;
    private String city;
    private String education;
    private String tags;
    //1在招 2已结束 0下架
    private Integer status;
    private Integer viewCount;
    private Integer applyCount;
    private LocalDateTime deadline;
    private String sourceUrl;
    private LocalDateTime createTime;
    private LocalDateTime updateTime;
    private Long createUser;
    private Long updateUser;
}
