package com.job.auth;

import com.alibaba.fastjson.JSONObject;
import com.job.context.BaseContext;
import com.job.controller.admin.AdminAgentController;
import com.job.controller.admin.EmployeeController;
import com.job.controller.user.AgentController;
import com.job.dto.AgentChatDTO;
import com.job.dto.AgentFeedbackDTO;
import com.job.entity.Employee;
import com.job.interceptor.JwtTokenAdminInterceptor;
import com.job.interceptor.JwtTokenUserInterceptor;
import com.job.mapper.AgentChatLogMapper;
import com.job.mapper.ResumeMapper;
import com.job.properties.JwtProperties;
import com.job.service.AgentService;
import com.job.service.EmployeeService;
import com.job.service.JobService;
import com.job.service.impl.AgentServiceImpl;
import com.job.utils.AgentClientUtil;
import com.job.utils.JwtUtil;
import com.job.utils.RedisLockHelper;
import com.job.vo.JobVO;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.http.MediaType;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Collections;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class LoginAgentAccessTest {
    @AfterEach void cleanup() { BaseContext.removeCurrentId(); }

    private JwtProperties properties() {
        JwtProperties p = new JwtProperties();
        p.setAdminSecretKey("YWRtaW4tdGVzdC1rZXktZm9yLWF1dGg=");
        p.setUserSecretKey("dXNlci10ZXN0LWtleS1mb3ItYXV0aA==");
        p.setAdminTokenName("token");
        p.setUserTokenName("authentication");
        p.setAdminTtl(3600000);
        return p;
    }

    @RestController
    static class BusinessProbe {
        @GetMapping("/admin/job/page") public String page() {
            return BaseContext.getCurrentRole() + ":" + BaseContext.getCurrentId();
        }
    }

    @Test void oneRealLoginTokenAccessesBusinessAndEveryAdminAgentEndpoint() throws Exception {
        JwtProperties p = properties();
        EmployeeService employees = mock(EmployeeService.class);
        Employee employee = new Employee();
        employee.setId(1L); employee.setName("Admin"); employee.setUsername("admin");
        when(employees.login(any())).thenReturn(employee);
        EmployeeController login = new EmployeeController();
        ReflectionTestUtils.setField(login, "employeeService", employees);
        ReflectionTestUtils.setField(login, "jwtProperties", p);
        MockMvc loginMvc = MockMvcBuilders.standaloneSetup(login).build();
        String loginJson = loginMvc.perform(post("/admin/employee/login")
                .contentType(MediaType.APPLICATION_JSON).content("{\"username\":\"admin\",\"password\":\"test\"}"))
                .andExpect(status().isOk()).andReturn().getResponse().getContentAsString();
        String token = JSONObject.parseObject(loginJson).getJSONObject("data").getString("token");

        AgentService service = mock(AgentService.class);
        when(service.chat(any())).thenAnswer(inv -> {
            assertEquals(BaseContext.Role.ADMIN, BaseContext.getCurrentRole());
            assertEquals(-1L, BaseContext.getAgentId());
            return Collections.singletonMap("reply", "ok");
        });
        when(service.analyzeJob(anyLong())).thenReturn(Collections.singletonMap("reply", "analysis"));
        when(service.history(anyString())).thenReturn(Collections.emptyList());
        AdminAgentController admin = new AdminAgentController();
        ReflectionTestUtils.setField(admin, "agentService", service);
        AgentController user = new AgentController();
        ReflectionTestUtils.setField(user, "agentService", service);
        JwtTokenAdminInterceptor adminGuard = new JwtTokenAdminInterceptor();
        JwtTokenUserInterceptor userGuard = new JwtTokenUserInterceptor();
        ReflectionTestUtils.setField(adminGuard, "jwtProperties", p);
        ReflectionTestUtils.setField(userGuard, "jwtProperties", p);
        MockMvc adminMvc = MockMvcBuilders.standaloneSetup(admin, new BusinessProbe()).addInterceptors(adminGuard).build();
        MockMvc userMvc = MockMvcBuilders.standaloneSetup(user).addInterceptors(userGuard).build();

        adminMvc.perform(get("/admin/job/page").header("token", token)).andExpect(status().isOk()).andExpect(content().string("ADMIN:1"));
        assertNull(BaseContext.getCurrentId()); assertNull(BaseContext.getCurrentRole());
        adminMvc.perform(post("/admin/agent/chat").header("token", token).contentType(MediaType.APPLICATION_JSON)
                .content("{\"message\":\"hello\",\"sessionId\":\"s\"}" )).andExpect(status().isOk()).andExpect(jsonPath("$.data.reply").value("ok"));
        adminMvc.perform(get("/admin/agent/history").header("token", token).param("sessionId", "s")).andExpect(status().isOk());
        adminMvc.perform(post("/admin/agent/analyze").header("token", token).contentType(MediaType.APPLICATION_JSON)
                .content("{\"jobId\":1}")).andExpect(status().isOk());
        adminMvc.perform(post("/admin/agent/feedback").header("token", token).contentType(MediaType.APPLICATION_JSON)
                .content("{\"sessionId\":\"s\",\"rating\":1}")).andExpect(status().isOk());
        assertNull(BaseContext.getCurrentId());

        adminMvc.perform(get("/admin/agent/history").param("sessionId", "s")).andExpect(status().isUnauthorized());
        adminMvc.perform(get("/admin/agent/history").header("token", "invalid").param("sessionId", "s")).andExpect(status().isUnauthorized());
        String candidate = JwtUtil.createJWT(p.getUserSecretKey(), 3600000, new java.util.HashMap<>(Collections.singletonMap("userId", 1L)));
        adminMvc.perform(get("/admin/agent/history").header("token", candidate).param("sessionId", "s")).andExpect(status().isUnauthorized());
        userMvc.perform(get("/user/agent/history").header("authentication", token).param("sessionId", "s")).andExpect(status().isUnauthorized());
        userMvc.perform(get("/user/agent/history").header("authentication", candidate).param("sessionId", "s")).andExpect(status().isOk());
        String expired = JwtUtil.createJWT(p.getAdminSecretKey(), -60000, new java.util.HashMap<>(Collections.singletonMap("empId", 1L)));
        adminMvc.perform(get("/admin/agent/history").header("token", expired).param("sessionId", "s")).andExpect(status().isUnauthorized());
        assertNull(BaseContext.getCurrentId());
    }

    @Test void adminAndCandidateWithSameNumericIdHaveDifferentAgentHistoryAndCalls() {
        AgentServiceImpl service = new AgentServiceImpl();
        AgentClientUtil client = mock(AgentClientUtil.class);
        AgentChatLogMapper logs = mock(AgentChatLogMapper.class);
        ReflectionTestUtils.setField(service, "agentClientUtil", client);
        ReflectionTestUtils.setField(service, "agentChatLogMapper", logs);
        JSONObject response = new JSONObject(); response.put("reply", "ok");
        when(client.chat(anyString(), anyString(), anyLong())).thenReturn(response);
        AgentChatDTO dto = new AgentChatDTO(); dto.setSessionId("same"); dto.setMessage("hello");
        BaseContext.setCurrentIdentity(1L, BaseContext.Role.ADMIN);
        service.chat(dto); service.history("same");
        AgentFeedbackDTO feedback = new AgentFeedbackDTO(); feedback.setSessionId("same"); feedback.setRating(1);
        service.feedback(feedback);
        BaseContext.setCurrentIdentity(1L, BaseContext.Role.USER);
        service.chat(dto); service.history("same");
        verify(client).chat("same", "hello", -1L);
        verify(client).chat("same", "hello", 1L);
        verify(logs).listBySession(-1L, "same"); verify(logs).listBySession(1L, "same");
        verify(client).feedback(eq(-1L), isNull(), eq("same"), eq(1), isNull());
    }

    @SuppressWarnings("unchecked")
    @Test void adminJobAnalysisDoesNotRequireOrReadAnyCandidateResume() {
        AgentServiceImpl service = new AgentServiceImpl();
        ResumeMapper resumes = mock(ResumeMapper.class);
        JobService jobs = mock(JobService.class);
        AgentClientUtil client = mock(AgentClientUtil.class);
        AgentChatLogMapper logs = mock(AgentChatLogMapper.class);
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        ValueOperations<String, String> values = mock(ValueOperations.class);
        when(redis.opsForValue()).thenReturn(values);
        RedisLockHelper lock = mock(RedisLockHelper.class);
        when(lock.tryLock(anyString(), any())).thenReturn("lock-owner");
        when(jobs.getById(99L)).thenReturn(JobVO.builder().id(99L).title("Java").build());
        JSONObject result = new JSONObject(); result.put("answer", "Job requirements");
        when(client.analyze(eq(-1L), anyMap(), anyMap())).thenReturn(result);
        ReflectionTestUtils.setField(service, "resumeMapper", resumes);
        ReflectionTestUtils.setField(service, "jobService", jobs);
        ReflectionTestUtils.setField(service, "agentClientUtil", client);
        ReflectionTestUtils.setField(service, "agentChatLogMapper", logs);
        ReflectionTestUtils.setField(service, "stringRedisTemplate", redis);
        ReflectionTestUtils.setField(service, "redisLockHelper", lock);
        BaseContext.setCurrentIdentity(1L, BaseContext.Role.ADMIN);
        assertEquals("Job requirements", service.analyzeJob(99L).get("reply"));
        verifyNoInteractions(resumes);
        verify(client).analyze(eq(-1L), anyMap(), argThat(java.util.Map::isEmpty));
        verify(values, atLeastOnce()).get("job:ai:analysis:-1:99");
        verify(lock).unlock("job:analyze:-1:99", "lock-owner");
    }
}
