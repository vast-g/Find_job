-- =====================================================
-- 国企/央企求职平台 数据库建表脚本
-- 数据库：job_platform
-- =====================================================
CREATE DATABASE IF NOT EXISTS job_platform DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
USE job_platform;

-- 1. 员工（管理端账号：平台管理员 + 企业 HR）
DROP TABLE IF EXISTS employee;
CREATE TABLE employee (
    id          BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    username    VARCHAR(32)  NOT NULL COMMENT '登录账号',
    password    VARCHAR(64)  NOT NULL COMMENT '密码(MD5)',
    name        VARCHAR(32)  NOT NULL COMMENT '姓名',
    company_id  BIGINT       NULL COMMENT '所属企业id(平台管理员为空)',
    status      INT          NOT NULL DEFAULT 1 COMMENT '状态 1启用 0禁用',
    create_time DATETIME     NULL,
    update_time DATETIME     NULL,
    create_user BIGINT       NULL,
    update_user BIGINT       NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='员工';

-- 2. 企业
DROP TABLE IF EXISTS company;
CREATE TABLE company (
    id          BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    name        VARCHAR(64)  NOT NULL COMMENT '企业名称',
    type        VARCHAR(32)  NULL COMMENT '企业类型(国企/央企/事业单位)',
    city        VARCHAR(32)  NULL COMMENT '所在城市',
    logo        VARCHAR(255) NULL COMMENT 'logo图片',
    description TEXT         NULL COMMENT '企业简介',
    status      INT          NOT NULL DEFAULT 1 COMMENT '状态 1正常 0停用',
    create_time DATETIME     NULL,
    update_time DATETIME     NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_name (name),
    KEY idx_type_city (type, city)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='企业';

-- 3. 岗位分类
DROP TABLE IF EXISTS job_category;
CREATE TABLE job_category (
    id          BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    name        VARCHAR(32)  NOT NULL COMMENT '分类名称',
    sort        INT          NOT NULL DEFAULT 0 COMMENT '排序',
    status      INT          NOT NULL DEFAULT 1 COMMENT '状态 1启用 0禁用',
    create_time DATETIME     NULL,
    update_time DATETIME     NULL,
    PRIMARY KEY (id),
    KEY idx_status_sort (status, sort)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='岗位分类';

-- 4. 岗位
DROP TABLE IF EXISTS job;
CREATE TABLE job (
    id          BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    company_id  BIGINT       NOT NULL COMMENT '企业id',
    category_id BIGINT       NOT NULL COMMENT '分类id',
    title       VARCHAR(64)  NOT NULL COMMENT '岗位名称',
    description TEXT         NULL COMMENT '岗位描述',
    requirement TEXT         NULL COMMENT '任职要求',
    salary_min  INT          NULL COMMENT '最低薪资(月薪/元)',
    salary_max  INT          NULL COMMENT '最高薪资(月薪/元)',
    city        VARCHAR(32)  NULL COMMENT '工作城市',
    education   VARCHAR(16)  NULL COMMENT '学历要求',
    tags        VARCHAR(255) NULL COMMENT '标签(逗号分隔:编制/五险一金/双休)',
    status      INT          NOT NULL DEFAULT 1 COMMENT '状态 1在招 2已结束 0下架',
    view_count  INT          NOT NULL DEFAULT 0 COMMENT '浏览量',
    apply_count INT          NOT NULL DEFAULT 0 COMMENT '投递量',
    deadline    DATETIME     NULL COMMENT '投递截止时间',
    create_time DATETIME     NULL,
    update_time DATETIME     NULL,
    create_user BIGINT       NULL,
    update_user BIGINT       NULL,
    PRIMARY KEY (id),
    KEY idx_company (company_id),
    KEY idx_category (category_id),
    KEY idx_status_city (status, city),
    KEY idx_deadline (deadline)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='岗位';

-- 5. 求职者
DROP TABLE IF EXISTS user;
CREATE TABLE user (
    id          BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    openid      VARCHAR(64)  NOT NULL COMMENT '微信openid',
    name        VARCHAR(32)  NULL COMMENT '昵称',
    phone       VARCHAR(11)  NULL COMMENT '手机号',
    avatar      VARCHAR(255) NULL COMMENT '头像',
    education   VARCHAR(16)  NULL COMMENT '学历',
    create_time DATETIME     NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_openid (openid)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='求职者';

-- 6. 简历
DROP TABLE IF EXISTS resume;
CREATE TABLE resume (
    id          BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    user_id     BIGINT       NOT NULL COMMENT '用户id',
    name        VARCHAR(32)  NULL COMMENT '姓名',
    education   VARCHAR(16)  NULL COMMENT '学历',
    school      VARCHAR(64)  NULL COMMENT '毕业院校',
    major       VARCHAR(64)  NULL COMMENT '专业',
    experience  TEXT         NULL COMMENT '工作/实习经历',
    skills      VARCHAR(255) NULL COMMENT '技能(逗号分隔)',
    summary     TEXT         NULL COMMENT '自我评价',
    is_default  INT          NOT NULL DEFAULT 0 COMMENT '是否默认 1是 0否',
    create_time DATETIME     NULL,
    update_time DATETIME     NULL,
    PRIMARY KEY (id),
    KEY idx_user_default (user_id, is_default)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='简历';

-- 7. 投递记录
DROP TABLE IF EXISTS application;
CREATE TABLE application (
    id             BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    user_id        BIGINT       NOT NULL COMMENT '用户id',
    job_id         BIGINT       NOT NULL COMMENT '岗位id',
    resume_id      BIGINT       NOT NULL COMMENT '简历id',
    status         INT          NOT NULL DEFAULT 1 COMMENT '状态 1已投递 2已查看 3面试邀请 4已录用 5已拒绝',
    interview_time DATETIME     NULL COMMENT '面试时间',
    remark         VARCHAR(255) NULL COMMENT '备注',
    create_time    DATETIME     NULL,
    update_time    DATETIME     NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_user_job (user_id, job_id),
    KEY idx_job_status (job_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='投递记录';

-- 8. 岗位收藏
DROP TABLE IF EXISTS job_favorite;
CREATE TABLE job_favorite (
    id          BIGINT   NOT NULL AUTO_INCREMENT COMMENT '主键',
    user_id     BIGINT   NOT NULL COMMENT '用户id',
    job_id      BIGINT   NOT NULL COMMENT '岗位id',
    create_time DATETIME NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_user_job (user_id, job_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='岗位收藏';

-- 9. AI 对话记录
DROP TABLE IF EXISTS agent_chat_log;
CREATE TABLE agent_chat_log (
    id          BIGINT      NOT NULL AUTO_INCREMENT COMMENT '主键',
    user_id     BIGINT      NOT NULL COMMENT '用户id',
    session_id  VARCHAR(64) NOT NULL COMMENT '会话id',
    role        VARCHAR(16) NOT NULL COMMENT '角色 user/assistant',
    content     TEXT        NULL COMMENT '内容',
    create_time DATETIME    NULL,
    PRIMARY KEY (id),
    KEY idx_user_session (user_id, session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI对话记录';

-- 初始数据：平台管理员账号（密码 123456 的 MD5）
INSERT INTO employee (username, password, name, company_id, status, create_time, update_time)
VALUES ('admin', 'e10adc3949ba59abbe56e057f20f883e', '平台管理员', NULL, 1, NOW(), NOW());
