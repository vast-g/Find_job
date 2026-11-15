package com.job.dto;

import lombok.Data;

import java.io.Serializable;
import java.time.LocalDateTime;

@Data
public class JobDTO implements Serializable {

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
    private Integer status;
    private LocalDateTime deadline;
}
