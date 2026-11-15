package com.job.dto;

import lombok.Data;

import java.io.Serializable;

@Data
public class ResumeDTO implements Serializable {

    private Long id;
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
}
