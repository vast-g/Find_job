package com.job.utils;

import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.JSONObject;
import com.job.constant.MessageConstant;
import com.job.exception.AgentBusinessException;
import com.job.properties.AgentProperties;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

import java.util.HashMap;
import java.util.Map;

/**
 * AI Agent 服务客户端，负责调用 Python 侧 FastAPI 接口
 */
@Component
public class AgentClientUtil {

    @Autowired
    private AgentProperties agentProperties;

    public JSONObject chat(String sessionId, String message, Long userId) {
        Map<String, Object> body = new HashMap<>();
        body.put("session_id", sessionId);
        body.put("message", message);
        body.put("user_id", userId);
        return post("/agent/chat", body);
    }

    public JSONObject recommend(Long userId, Integer topN) {
        Map<String, Object> body = new HashMap<>();
        body.put("user_id", userId);
        body.put("top_n", topN);
        return post("/agent/recommend", body);
    }

    public JSONObject analyze(Long userId, Map<String, Object> job, Map<String, Object> resume) {
        Map<String, Object> body = new HashMap<>();
        body.put("user_id", userId);
        body.put("job", job);
        body.put("resume", resume);
        return post("/agent/analyze", body);
    }

    public JSONObject feedback(Long userId, String requestId, String sessionId, Integer rating, String comment) {
        Map<String, Object> body = new HashMap<>();
        body.put("user_id", userId);
        body.put("request_id", requestId);
        body.put("session_id", sessionId);
        body.put("rating", rating);
        body.put("comment", comment);
        return post("/agent/feedback", body);
    }

    private JSONObject post(String path, Map<String, Object> body) {
        try {
            String url = agentProperties.getBaseUrl() + path;
            String json = HttpClientUtil.doPostJson(url, JSON.toJSONString(body));
            JSONObject result = JSON.parseObject(json);
            if (result == null || result.isEmpty()) {
                throw new AgentBusinessException(MessageConstant.AGENT_UNAVAILABLE);
            }
            if (result.containsKey("detail")) {
                Object detail = result.get("detail");
                throw new AgentBusinessException(detail instanceof String
                        ? (String) detail : MessageConstant.AGENT_UNAVAILABLE);
            }
            return result;
        } catch (AgentBusinessException e) {
            throw e;
        } catch (Exception e) {
            throw new AgentBusinessException(MessageConstant.AGENT_UNAVAILABLE);
        }
    }
}
