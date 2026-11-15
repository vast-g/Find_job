package com.job.dto;

import lombok.Data;

import java.io.Serializable;

@Data
public class JobCategoryDTO implements Serializable {

    private Long id;
    private String name;
    private Integer sort;
    private Integer status;

    private int page;
    private int pageSize;
}
