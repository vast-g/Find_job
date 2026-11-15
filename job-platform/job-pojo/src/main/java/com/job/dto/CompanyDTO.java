package com.job.dto;

import lombok.Data;

import java.io.Serializable;

@Data
public class CompanyDTO implements Serializable {

    private Long id;
    private String name;
    private String type;
    private String city;
    private String logo;
    private String description;
    private Integer status;
}
