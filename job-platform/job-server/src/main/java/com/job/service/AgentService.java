package com.job.service;

import com.job.dto.AgentChatDTO;
import com.job.dto.AgentFeedbackDTO;
import com.job.entity.AgentChatLog;
import com.job.vo.JobVO;

import java.util.List;
import java.util.Map;

public interface AgentService {

    Map<String, Object> chat(AgentChatDTO agentChatDTO);

    List<AgentChatLog> history(String sessionId);

    List<JobVO> recommend(Integer topN);

    Map<String, Object> analyzeJob(Long jobId);

    void feedback(AgentFeedbackDTO agentFeedbackDTO);
}
