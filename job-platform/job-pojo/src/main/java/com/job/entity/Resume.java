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
public class Resume implements Serializable {

    private static final long serialVersionUID = 1L;

    private Long id;
    private Long userId;
    private String name;
    private String education;
    private String school;
    private String major;
    private String experience;
    private String skills;
    private String summary;
    private Integer age;
    private String educationExperience;
    private String projectExperience;
    private String campusExperience;
    private String jobStatus;
    private String expectPosition;
    private String expectCity;
    private String expectSalary;
    private String expectIndustry;
    private String clubExperience;
    private String honors;
    private String certificates;
    private Integer isDefault;
    private LocalDateTime createTime;
    private LocalDateTime updateTime;
}
