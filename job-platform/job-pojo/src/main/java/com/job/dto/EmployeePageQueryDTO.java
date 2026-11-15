package com.job.dto;

import lombok.Data;

import java.io.Serializable;

@Data
public class EmployeePageQueryDTO implements Serializable {

    private int page;
    private int pageSize;
    private String name;
    private Integer status;
}
