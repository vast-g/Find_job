package com.job.dto;

import lombok.Data;

import java.io.Serializable;

@Data
public class JobPageQueryDTO implements Serializable {

    private int page;
    private int pageSize;
    private String title;
    private Long categoryId;
    private Integer status;
    private String city;
    private Long companyId;
}
