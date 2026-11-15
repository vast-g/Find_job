package com.job.properties;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

@Component
@ConfigurationProperties(prefix = "job.agent")
@Data
public class AgentProperties {

    private String baseUrl;
}
