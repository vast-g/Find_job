package com.job.controller.admin;

import com.job.dto.AgentAnalyzeDTO;
import com.job.dto.AgentChatDTO;
import com.job.dto.AgentFeedbackDTO;
import com.job.entity.AgentChatLog;
import com.job.result.Result;
import com.job.service.AgentService;
import com.job.vo.JobVO;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/**
 * Uses the same verified administrator login as all other /admin endpoints.
 * AgentService derives an isolated Agent ID from the authenticated role and ID;
 * administrator sessions never borrow a candidate's resume or conversation.
 */
@RestController
@RequestMapping("/admin/agent")
@Api(tags = "AI求职助手接口（管理端）")
public class AdminAgentController {

    @Autowired
    private AgentService agentService;

    @PostMapping("/chat")
    @ApiOperation("AI对话（管理端）")
    public Result<Map<String, Object>> chat(@RequestBody AgentChatDTO dto) {
        return Result.success(agentService.chat(dto));
    }

    @PostMapping("/analyze")
    @ApiOperation("岗位要求与准备方向分析（管理端，不读取求职用户简历）")
    public Result<Map<String, Object>> analyze(@RequestBody AgentAnalyzeDTO dto) {
        return Result.success(agentService.analyzeJob(dto.getJobId()));
    }

    @PostMapping("/feedback")
    @ApiOperation("AI回答反馈（管理端）")
    public Result<Object> feedback(@RequestBody AgentFeedbackDTO dto) {
        agentService.feedback(dto);
        return Result.success();
    }

    @GetMapping("/history")
    @ApiOperation("当前管理员对话历史")
    public Result<List<AgentChatLog>> history(@RequestParam String sessionId) {
        return Result.success(agentService.history(sessionId));
    }

    @GetMapping("/recommend")
    @ApiOperation("岗位推荐（管理端）")
    public Result<List<JobVO>> recommend(@RequestParam(required = false) Integer topN) {
        return Result.success(agentService.recommend(topN));
    }
}
