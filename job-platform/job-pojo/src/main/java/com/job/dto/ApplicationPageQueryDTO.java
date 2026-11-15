package com.job.dto;

import lombok.Data;

import java.io.Serializable;

@Data
public class ApplicationPageQueryDTO implements Serializable {

    private int page;
    private int pageSize;
    private Long jobId;
    private Integer status;
}
