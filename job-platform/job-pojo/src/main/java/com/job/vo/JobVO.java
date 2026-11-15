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
public class JobVO implements Serializable {

    private Long id;
    private Long companyId;
    private String companyName;
    private Long categoryId;
    private String categoryName;
    private String title;
    private String description;
    private String requirement;
    private Integer salaryMin;
    private Integer salaryMax;
    private String city;
    private String education;
    private String tags;
    private Integer status;
    private Integer viewCount;
    private Integer applyCount;
    private LocalDateTime deadline;
    private String sourceUrl;
    private LocalDateTime createTime;
}
