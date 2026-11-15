package com.job.dto;

import lombok.Data;

import java.io.Serializable;

@Data
public class AgentFeedbackDTO implements Serializable {

    private String sessionId;
    private String requestId;
    private Integer rating;
    private String comment;
}
