package com.job.service.impl;

import com.alibaba.fastjson.JSONArray;
import com.alibaba.fastjson.JSONObject;
import com.job.constant.MessageConstant;
import com.job.context.BaseContext;
import com.job.dto.AgentChatDTO;
import com.job.dto.AgentFeedbackDTO;
import com.job.entity.AgentChatLog;
import com.job.entity.Resume;
import com.job.exception.JobBusinessException;
import com.job.exception.ResumeBusinessException;
import com.job.mapper.ResumeMapper;
import com.job.service.AgentService;
import com.job.service.JobService;
import com.job.utils.AgentClientUtil;
import com.job.utils.RedisLockHelper;
import com.job.vo.JobVO;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

@Service
public class AgentServiceImpl implements AgentService {

    @Autowired
    private AgentClientUtil agentClientUtil;
    @Autowired
    private com.job.mapper.AgentChatLogMapper agentChatLogMapper;
    @Autowired
    private JobService jobService;
    @Autowired
    private ResumeMapper resumeMapper;
    /** AI 岗位分析的分布式锁：同一「用户 × 岗位」同时只允许一次大模型调用。 */
    @Autowired
    private RedisLockHelper redisLockHelper;
    /** 分析结果缓存用。这里直接用 StringRedisTemplate 存纯文本，不引入额外序列化。 */
    @Autowired
    private StringRedisTemplate stringRedisTemplate;

    /**
     * 分析结果缓存前缀。key = 前缀 + userId + ":" + jobId。
     *
     * <p>为什么要带 userId：分析结论是「**这份简历**对上**这个岗位**」的匹配结果，
     * 换个人看同一个岗位结论就不同，只按 jobId 缓存会串数据。
     */
    private static final String AI_ANALYSIS_PREFIX = "job:ai:analysis:";

    /**
     * 分析结果缓存 TTL（6 小时）。
     *
     * <p>为什么能缓存：一次分析要调大模型（几十秒 + 真金白银），而同一份简历
     * 对同一个岗位的分析结论短时间内不会变。缓存把"重复点击"的成本降到零。
     * 为什么是 6 小时而不是更长：简历一更新结论就该重算，6 小时是个折中。
     */
    private static final Duration AI_ANALYSIS_TTL = Duration.ofHours(6);

    /** 分析锁名前缀。 */
    private static final String LOCK_ANALYZE_PREFIX = "job:analyze:";

    /** 分析锁 TTL：一次大模型调用通常 20~60 秒，给 3 分钟兜底。 */
    private static final Duration ANALYZE_LOCK_TTL = Duration.ofMinutes(3);

    /** 没抢到锁时，等对方算完的轮询次数与间隔（6 × 500ms = 最多等 3 秒）。 */
    private static final int ANALYZE_WAIT_POLLS = 6;
    private static final long ANALYZE_WAIT_MILLIS = 500L;

    @Override
    public Map<String, Object> chat(AgentChatDTO agentChatDTO) {
        Long userId = BaseContext.getAgentId();
        String sessionId = agentChatDTO.getSessionId();
        if (sessionId == null || sessionId.isEmpty()) {
            sessionId = UUID.randomUUID().toString().replace("-", "");
        }

        // 1. 保存用户消息
        saveLog(userId, sessionId, "user", agentChatDTO.getMessage());

        // 2. 调用 Agent 服务
        JSONObject resp = agentClientUtil.chat(sessionId, agentChatDTO.getMessage(), userId);
        String reply = resp == null ? null : resp.getString("reply");
        JSONArray sources = resp == null ? null : resp.getJSONArray("sources");
        String requestId = resp == null ? null : resp.getString("request_id");

        // 3. 保存 AI 回复
        saveLog(userId, sessionId, "assistant", reply);

        Map<String, Object> result = new HashMap<>();
        result.put("sessionId", sessionId);
        result.put("reply", reply);
        result.put("sources", sources);
        result.put("requestId", requestId);
        return result;
    }

    @Override
    public void feedback(AgentFeedbackDTO agentFeedbackDTO) {
        Long userId = BaseContext.getAgentId();
        agentClientUtil.feedback(userId, agentFeedbackDTO.getRequestId(), agentFeedbackDTO.getSessionId(),
                agentFeedbackDTO.getRating(), agentFeedbackDTO.getComment());
    }

    @Override
    public List<AgentChatLog> history(String sessionId) {
        return agentChatLogMapper.listBySession(BaseContext.getAgentId(), sessionId);
    }

    @Override
    public List<JobVO> recommend(Integer topN) {
        Long userId = BaseContext.getAgentId();
        JSONObject resp = agentClientUtil.recommend(userId, topN == null ? 10 : topN);
        List<JobVO> list = new ArrayList<>();
        if (resp == null) {
            return list;
        }
        JSONArray jobIds = resp.getJSONArray("job_ids");
        if (jobIds == null) {
            return list;
        }
        for (int i = 0; i < jobIds.size(); i++) {
            Long jobId = jobIds.getLong(i);
            try {
                list.add(jobService.getById(jobId));
            } catch (Exception ignored) {
            }
        }
        return list;
    }

    @Override
    public Map<String, Object> analyzeJob(Long jobId) {
        Long userId = BaseContext.getAgentId();

        JobVO job = jobService.getById(jobId);

        // Administrators analyze the job itself; candidate matching uses their own resume.
        Resume resume = null;
        if (userId > 0) {
            resume = resumeMapper.getDefault(userId);
            if (resume == null) {
                List<Resume> resumes = resumeMapper.listByUserId(userId);
                resume = (resumes == null || resumes.isEmpty()) ? null : resumes.get(0);
            }
            if (resume == null) {
                throw new ResumeBusinessException(MessageConstant.RESUME_NOT_FOUND);
            }
        }

        String sessionId = UUID.randomUUID().toString().replace("-", "");
        saveLog(userId, sessionId, "user", userId < 0
                ? "请分析「" + job.getTitle() + "」岗位的要求、准备方向与面试重点"
                : "请结合我的简历和「" + job.getTitle() + "」岗位的任职要求，给我一份综合分析");

        String reply = analyzeWithCacheAndLock(userId, jobId, job, resume);

        saveLog(userId, sessionId, "assistant", reply);

        Map<String, Object> result = new HashMap<>();
        result.put("sessionId", sessionId);
        result.put("reply", reply);
        return result;
    }

    /**
     * 带「结果缓存 + 分布式锁」的岗位分析。
     *
     * <h3>为什么不能只加锁</h3>
     * 这个操作太贵（一次大模型调用几十秒 + 真实费用）。只加锁的问题是：
     * 第二个请求排队等到锁释放后，**还是要自己重新算一遍** —— 因为它没有结果可读。
     * 所以必须「锁 + 结果缓存」配合：
     * <ol>
     *   <li>先查缓存，命中直接返回（绝大多数重复点击走这条路，零成本）</li>
     *   <li>未命中 → 抢锁。抢到的人去调大模型，算完写缓存</li>
     *   <li>没抢到的人**轮询等缓存**（最多 3 秒），拿到就返回，避免重复烧钱</li>
     *   <li>等不到（对方可能失败了）→ 降级：自己算一次，保证请求能返回</li>
     * </ol>
     *
     * <p>这就是"**可用性优先于完美互斥**"的取舍：宁可极少数情况下多算一次，
     * 也不让用户干等或者报错。
     */
    private String analyzeWithCacheAndLock(Long userId, Long jobId, JobVO job, Resume resume) {
        String cacheKey = AI_ANALYSIS_PREFIX + userId + ":" + jobId;
        String cached = stringRedisTemplate.opsForValue().get(cacheKey);
        if (cached != null && !cached.isEmpty()) {
            return cached;
        }

        String lockKey = LOCK_ANALYZE_PREFIX + userId + ":" + jobId;
        String token = redisLockHelper.tryLock(lockKey, ANALYZE_LOCK_TTL);
        try {
            if (token == null) {
                // 有人在算了：轮询等它写缓存，拿到就返回（不重复调大模型）
                for (int i = 0; i < ANALYZE_WAIT_POLLS; i++) {
                    sleepQuietly(ANALYZE_WAIT_MILLIS);
                    cached = stringRedisTemplate.opsForValue().get(cacheKey);
                    if (cached != null && !cached.isEmpty()) {
                        return cached;
                    }
                }
                // 等不到 → 降级自己算，不让用户一直等
            }

            // 双重检查：等锁 / 抢锁期间可能已经有人算完并写了缓存
            cached = stringRedisTemplate.opsForValue().get(cacheKey);
            if (cached != null && !cached.isEmpty()) {
                return cached;
            }

            JSONObject resp = agentClientUtil.analyze(
                    userId, buildJobMap(job), buildResumeMap(resume));
            String reply = resp == null ? null : resp.getString("answer");
            if (reply == null) {
                reply = "";
            }
            // 只有真拿到内容才缓存：空结果缓存下来会让用户 6 小时内一直看到空
            if (!reply.isEmpty()) {
                stringRedisTemplate.opsForValue().set(cacheKey, reply, AI_ANALYSIS_TTL);
            }
            return reply;
        } finally {
            // 只有自己抢到锁才需要释放；没抢到时 token 为 null，unlock 会直接返回
            redisLockHelper.unlock(lockKey, token);
        }
    }

    /** 短暂休眠；被中断就恢复中断标记并提前返回。 */
    private void sleepQuietly(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    private Map<String, Object> buildJobMap(JobVO job) {
        Map<String, Object> m = new HashMap<>();
        m.put("title", job.getTitle());
        m.put("companyName", job.getCompanyName());
        m.put("city", job.getCity());
        m.put("education", job.getEducation());
        m.put("salaryMin", job.getSalaryMin());
        m.put("salaryMax", job.getSalaryMax());
        m.put("tags", job.getTags());
        m.put("description", job.getDescription());
        m.put("requirement", job.getRequirement());
        return m;
    }

    private Map<String, Object> buildResumeMap(Resume r) {
        Map<String, Object> m = new HashMap<>();
        if (r == null) {
            return m;
        }
        m.put("name", r.getName());
        m.put("education", r.getEducation());
        m.put("school", r.getSchool());
        m.put("major", r.getMajor());
        m.put("skills", r.getSkills());
        m.put("summary", r.getSummary());
        m.put("experience", r.getExperience());
        m.put("projectExperience", r.getProjectExperience());
        m.put("campusExperience", r.getCampusExperience());
        m.put("educationExperience", r.getEducationExperience());
        m.put("jobStatus", r.getJobStatus());
        m.put("expectPosition", r.getExpectPosition());
        m.put("expectCity", r.getExpectCity());
        m.put("expectSalary", r.getExpectSalary());
        m.put("expectIndustry", r.getExpectIndustry());
        m.put("clubExperience", r.getClubExperience());
        m.put("honors", r.getHonors());
        m.put("certificates", r.getCertificates());
        m.put("age", r.getAge());
        return m;
    }

    private void saveLog(Long userId, String sessionId, String role, String content) {
        AgentChatLog log = AgentChatLog.builder()
                .userId(userId)
                .sessionId(sessionId)
                .role(role)
                .content(content)
                .createTime(LocalDateTime.now())
                .build();
        agentChatLogMapper.insert(log);
    }
}
