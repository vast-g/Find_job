package com.job.auth;

import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.JSONObject;
import com.job.constant.MessageConstant;
import com.job.exception.AgentBusinessException;
import com.job.properties.AgentProperties;
import com.job.utils.AgentClientUtil;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;

/** Exercises the real HTTP transport against a temporary loopback server. */
class AgentClientErrorTest {
    private HttpServer server;
    private AgentClientUtil client;
    private volatile int responseStatus;
    private volatile String responseBody;
    private final AtomicReference<JSONObject> requestBody = new AtomicReference<>();
    private final AtomicReference<String> requestMethod = new AtomicReference<>();

    @BeforeEach
    void startServer() throws Exception {
        responseStatus = 200;
        responseBody = "{\"reply\":\"answer\",\"session_id\":\"same\"}";
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/agent/chat", exchange -> {
            try {
                requestMethod.set(exchange.getRequestMethod());
                requestBody.set(JSON.parseObject(new String(
                        exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8)));
                byte[] response = responseBody.getBytes(StandardCharsets.UTF_8);
                exchange.getResponseHeaders().set("Content-Type", "application/json; charset=UTF-8");
                exchange.sendResponseHeaders(responseStatus, response.length == 0 ? -1 : response.length);
                if (response.length > 0) {
                    exchange.getResponseBody().write(response);
                }
            } finally {
                exchange.close();
            }
        });
        server.start();
        AgentProperties properties = new AgentProperties();
        properties.setBaseUrl("http://127.0.0.1:" + server.getAddress().getPort());
        client = new AgentClientUtil();
        ReflectionTestUtils.setField(client, "agentProperties", properties);
    }

    @AfterEach
    void stopServer() {
        if (server != null) {
            server.stop(0);
        }
    }

    private AgentBusinessException failure(int status, String body) {
        responseStatus = status;
        responseBody = body;
        return assertThrows(AgentBusinessException.class,
                () -> client.chat("same", "question", 7L));
    }

    @Test
    void busyConflictPreservesPythonDetailInsteadOfReturningSuccess() {
        String detail = "当前会话正在处理上一条请求，请稍后重试";
        JSONObject body = new JSONObject();
        body.put("detail", detail);
        assertEquals(detail, failure(409, body.toJSONString()).getMessage());
    }

    @Test
    void unavailableResponsePreservesStringDetail() {
        assertEquals("Memory service unavailable",
                failure(503, "{\"detail\":\"Memory service unavailable\"}").getMessage());
    }

    @Test
    void structuredValidationDetailsUseGenericBusinessError() {
        assertEquals(MessageConstant.AGENT_UNAVAILABLE,
                failure(422, "{\"detail\":[{\"loc\":[\"body\",\"message\"],\"msg\":\"Field required\"}]}").getMessage());
        assertEquals(MessageConstant.AGENT_UNAVAILABLE,
                failure(503, "{\"detail\":{\"reason\":\"internal error\"}}").getMessage());
        assertEquals(MessageConstant.AGENT_UNAVAILABLE,
                failure(503, "{\"detail\":null}").getMessage());
    }

    @Test
    void detailIsRejectedEvenInAnOtherwiseSuccessfulResponse() {
        assertEquals("retry later",
                failure(200, "{\"reply\":\"should not escape\",\"detail\":\"retry later\"}").getMessage());
    }

    @Test
    void emptyNullAndEmptyObjectResponsesAreUnavailable() {
        for (String body : new String[]{"", "   ", "null", "{}"}) {
            assertEquals(MessageConstant.AGENT_UNAVAILABLE,
                    failure(200, body).getMessage(), "body=" + body);
        }
    }

    @Test
    void malformedAndNonJsonServiceErrorsAreUnavailable() {
        assertEquals(MessageConstant.AGENT_UNAVAILABLE,
                failure(503, "<html>Service unavailable</html>").getMessage());
        assertEquals(MessageConstant.AGENT_UNAVAILABLE,
                failure(200, "{broken json").getMessage());
        assertEquals(MessageConstant.AGENT_UNAVAILABLE,
                failure(503, "").getMessage());
    }

    @Test
    void successfulReplyAndRequestIdentityPassThroughRealTransport() {
        JSONObject result = client.chat("same", "question", -7L);
        assertNotNull(result);
        assertEquals("answer", result.getString("reply"));
        assertEquals("same", result.getString("session_id"));
        assertEquals("POST", requestMethod.get());
        assertEquals("same", requestBody.get().getString("session_id"));
        assertEquals("question", requestBody.get().getString("message"));
        assertEquals(-7L, requestBody.get().getLongValue("user_id"));
    }
}
