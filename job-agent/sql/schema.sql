-- 求职系统 AI Agent 数据库
CREATE DATABASE IF NOT EXISTS job_agent DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
USE job_agent;

-- 1. 对话消息（短期记忆）
DROP TABLE IF EXISTS message;
CREATE TABLE message (
    id            BIGINT       NOT NULL AUTO_INCREMENT,
    session_id    VARCHAR(64)  NOT NULL COMMENT '会话id',
    user_id       BIGINT       NOT NULL COMMENT '用户id',
    role          VARCHAR(16)  NOT NULL COMMENT 'user/assistant/tool/system',
    content       TEXT         NULL,
    turn          INT          NOT NULL DEFAULT 0 COMMENT '轮次(第几轮对话)',
    create_time   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_session_turn (session_id, turn),
    KEY idx_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='对话消息';

-- 2. 用户画像（长期记忆）
DROP TABLE IF EXISTS user_profile;
CREATE TABLE user_profile (
    id                 BIGINT       NOT NULL AUTO_INCREMENT,
    user_id            BIGINT       NOT NULL,
    resume_summary     TEXT         NULL COMMENT '简历摘要',
    preferences        JSON         NULL COMMENT '偏好(城市/薪资/行业)',
    goals              TEXT         NULL COMMENT '求职目标',
    skills             JSON         NULL COMMENT '技能标签',
    cross_session_summary TEXT      NULL COMMENT '跨会话摘要',
    summary_updated_at DATETIME     NULL,
    create_time        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户长期画像';

-- 3. 摘要反馈（用于摘要错误修复）
DROP TABLE IF EXISTS summary_feedback;
CREATE TABLE summary_feedback (
    id           BIGINT      NOT NULL AUTO_INCREMENT,
    user_id      BIGINT      NOT NULL,
    summary_text TEXT        NULL COMMENT '被反馈的摘要',
    rating       TINYINT     NOT NULL COMMENT '1有效 0无效',
    correction   TEXT        NULL COMMENT '人工修正',
    create_time  DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='摘要反馈';

-- 4. Agent 执行轨迹（可观测性）
DROP TABLE IF EXISTS agent_trace;
CREATE TABLE agent_trace (
    id          BIGINT       NOT NULL AUTO_INCREMENT,
    request_id  VARCHAR(64)  NOT NULL COMMENT '请求id',
    session_id  VARCHAR(64)  NULL,
    user_id     BIGINT       NULL,
    step        INT          NOT NULL COMMENT '步骤序号',
    node        VARCHAR(64)  NULL COMMENT '节点名(entry/intent/orchestrator/rag/tool/llm)',
    input       TEXT         NULL,
    output      TEXT         NULL,
    model_used  VARCHAR(64)  NULL,
    cost_time_ms INT         NULL,
    error       VARCHAR(512) NULL,
    create_time DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_request (request_id, step),
    KEY idx_user_time (user_id, create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Agent执行轨迹';

-- 5. Benchmark 评测集
DROP TABLE IF EXISTS benchmark_case;
CREATE TABLE benchmark_case (
    id            BIGINT       NOT NULL AUTO_INCREMENT,
    category      VARCHAR(32)  NOT NULL COMMENT '推荐/简历优化/面试问答/进度追踪/对抗性',
    question      TEXT         NOT NULL,
    expected      JSON         NULL COMMENT '期望答案/关键点',
    golden_tools  JSON         NULL COMMENT '期望调用的工具',
    ground_truth_docs JSON     NULL COMMENT 'golden 检索文档',
    adversarial   TINYINT      NOT NULL DEFAULT 0 COMMENT '是否对抗性',
    difficulty    TINYINT      NOT NULL DEFAULT 1 COMMENT '难度1-3',
    create_time   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_category (category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='评测集';

-- 6. Benchmark 评测结果（回归记录）
DROP TABLE IF EXISTS benchmark_run;
CREATE TABLE benchmark_run (
    id          BIGINT       NOT NULL AUTO_INCREMENT,
    run_tag     VARCHAR(64)  NOT NULL COMMENT '运行标识(如 prompt_v2_20260920)',
    commit_sha  VARCHAR(64)  NULL,
    metrics     JSON         NULL COMMENT '指标汇总',
    report_path VARCHAR(255) NULL,
    create_time DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_tag (run_tag)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='评测运行记录';

-- 7. 求职知识库文档（RAG 语料）
DROP TABLE IF EXISTS knowledge_doc;
CREATE TABLE knowledge_doc (
    id          BIGINT       NOT NULL AUTO_INCREMENT,
    doc_id      VARCHAR(64)  NOT NULL,
    title       VARCHAR(255) NULL,
    content     TEXT         NOT NULL,
    chunk_index INT          NOT NULL DEFAULT 0 COMMENT '分块序号',
    chunk_size  INT          NOT NULL DEFAULT 200 COMMENT '该块使用的chunk_size(A/B测试)',
    source      VARCHAR(255) NULL COMMENT '来源',
    create_time DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_doc (doc_id, chunk_index)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='知识库文档分块';
