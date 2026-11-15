package com.job.controller.user;

import com.job.dto.AgentAnalyzeDTO;
import com.job.dto.AgentChatDTO;
import com.job.dto.AgentFeedbackDTO;
import com.job.entity.AgentChatLog;
import com.job.result.Result;
import com.job.service.AgentService;
import com.job.vo.JobVO;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/user/agent")
@Api(tags = "AI求职助手接口")
@Slf4j
public class AgentController {

    @Autowired
    private AgentService agentService;

    @PostMapping("/chat")
    @ApiOperation("AI对话")
    public Result<Map<String, Object>> chat(@RequestBody AgentChatDTO agentChatDTO) {
        return Result.success(agentService.chat(agentChatDTO));
    }

    @PostMapping("/analyze")
    @ApiOperation("AI岗位分析")
    public Result<Map<String, Object>> analyze(@RequestBody AgentAnalyzeDTO agentAnalyzeDTO) {
        return Result.success(agentService.analyzeJob(agentAnalyzeDTO.getJobId()));
    }

    @PostMapping("/feedback")
    @ApiOperation("AI回答反馈")
    public Result<Object> feedback(@RequestBody AgentFeedbackDTO agentFeedbackDTO) {
        agentService.feedback(agentFeedbackDTO);
        return Result.success();
    }

    @GetMapping("/history")
    @ApiOperation("对话历史")
    public Result<List<AgentChatLog>> history(@RequestParam String sessionId) {
        return Result.success(agentService.history(sessionId));
    }

    @GetMapping("/recommend")
    @ApiOperation("岗位推荐")
    public Result<List<JobVO>> recommend(@RequestParam(required = false) Integer topN) {
        return Result.success(agentService.recommend(topN));
    }
}
