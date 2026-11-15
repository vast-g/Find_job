package com.job.dto;

import lombok.Data;

import java.io.Serializable;

@Data
public class CompanyPageQueryDTO implements Serializable {

    private int page;
    private int pageSize;
    private String name;
    private String type;
    private Integer status;
}
