package com.job.dto;

import lombok.Data;

import java.io.Serializable;

@Data
public class ApplicationSubmitDTO implements Serializable {

    private Long jobId;
    private Long resumeId;
}
