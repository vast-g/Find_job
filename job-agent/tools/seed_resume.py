"""给评测用户补一份完整简历。

## 为什么需要

`resume` 表里只有一行，24 个字段里**填了 6 个**，且都是 id/时间戳之类的系统字段：
name、education、school、major、skills、expect_position 等**全部为 NULL**，
club_experience 还是占位测试数据 `[{"name":"111","role":"22","description":"33"}]`。

后果：「简历优化」类用例（15 条）**没有简历可优化** ——
Agent 只能输出通用建议，Task Completion 长期只有 26.7%。
这与「岗位推荐」缺岗位数据是同一类问题（数据缺失被误读为模型能力不足）。

## 格式说明（按小程序端的实际用法对齐）

| 字段 | 格式 | 依据 |
|---|---|---|
| `experience` | JSON 数组，项含 company/position/... | `workAdd.js: JSON.parse(r.experience)` |
| `projectExperience` | JSON 数组 | `resume.js: LISTS.project` |
| `clubExperience` | JSON 数组 | `clubAdd.js: JSON.parse(r.clubExperience)` |
| `honors` / `certificates` | JSON 数组（字符串项） | `honorSelect.js / certSelect.js` |
| `educationExperience` | **纯文本** | `resume.js: { key:'educationExperience', textarea:true }` |
| `skills` | 逗号分隔 | `get_user_resume` 按 "," 拆分 |

写错格式不会影响 Agent（它只是把文本读给模型），但会让小程序的简历页渲染不出来，
所以这里严格对齐。

用法：
    python tools/seed_resume.py --dry-run
    python tools/seed_resume.py
    python tools/seed_resume.py --show
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "benchmark" / "reports" / "resume_seed.txt"
OUT.parent.mkdir(parents=True, exist_ok=True)
_fh = OUT.open("w", encoding="utf-8")


class Tee:
    def write(self, s):
        _fh.write(s)

    def flush(self):
        _fh.flush()


sys.stdout = Tee()
sys.stderr = Tee()

TARGET_USER_ID = 1
MARK = "[seed]"   # 用自我评价开头做标记，便于识别这是补的数据


RESUME = {
    "name": "张明",
    "age": 24,
    "education": "硕士",
    "school": "北京邮电大学",
    "major": "计算机科学与技术",
    "job_status": "在校-月内到岗",
    "skills": "Python,Java,SQL,PyTorch,LangChain,Docker,Redis,MySQL,Linux,Git",
    "summary": (
        f"{MARK} 计算机硕士应届生，研究方向为自然语言处理与大模型应用。"
        "熟悉 RAG 检索增强与 Agent 编排，有两段算法实习经历，"
        "主导过企业内部知识问答系统的检索链路优化。"
        "求职方向为国企/央企的算法工程师或软件开发工程师，期望在北京发展。"
    ),
    "experience": json.dumps([
        {
            "company": "中国电信数字智能科技分公司",
            "position": "算法实习生",
            "startTime": "2025-07-01",
            "endTime": "2025-12-31",
            "description": (
                "1. 参与企业内部知识问答系统的检索链路建设，负责文本切分与向量化管线；"
                "2. 对比稠密检索与 BM25 混合检索效果，将答疑准确率提升约 18%；"
                "3. 使用 LangChain 搭建工具调用型 Agent，支撑工单自动分类场景。"
            ),
        },
        {
            "company": "北京字节跳动科技有限公司",
            "position": "后端开发实习生",
            "startTime": "2024-07-01",
            "endTime": "2024-10-31",
            "description": (
                "1. 参与内容审核后台的接口开发与性能优化，日均调用量约 200 万；"
                "2. 使用 Redis 缓存热点数据，接口 P99 延迟从 320ms 降至 90ms。"
            ),
        },
    ], ensure_ascii=False),
    "project_experience": json.dumps([
        {
            "name": "面向国企招聘的智能求职助手",
            "role": "独立开发",
            "startTime": "2025-03-01",
            "endTime": "2025-09-30",
            "description": (
                "基于 LangGraph 构建 ReAct Agent，支持岗位推荐、简历诊断与面试问答；"
                "检索侧采用 FAISS 稠密检索 + BM25 稀疏检索的 RRF 融合，"
                "自建评测集量化 Recall@K 与忠实度，并用 Bad Case 驱动迭代。"
            ),
        },
        {
            "name": "中文长文本摘要模型微调",
            "role": "核心成员",
            "startTime": "2024-11-01",
            "endTime": "2025-05-31",
            "description": (
                "基于 Qwen 系列模型做 LoRA 微调，构建 3 万条中文长文摘要数据集，"
                "ROUGE-L 相比基线提升 6.2 个点。"
            ),
        },
    ], ensure_ascii=False),
    "education_experience": (
        "2023.09 - 2026.06  北京邮电大学  计算机科学与技术  硕士\n"
        "主修课程：自然语言处理、机器学习、分布式系统、算法设计与分析\n"
        "2019.09 - 2023.06  北京邮电大学  软件工程  本科\n"
        "主修课程：数据结构、操作系统、数据库原理、计算机网络"
    ),
    "campus_experience": (
        "2024.09 - 2025.06  校研究生会技术部  部长\n"
        "负责校内活动报名系统的开发与维护，服务师生约 8000 人次。"
    ),
    "club_experience": json.dumps([
        {
            "name": "北邮开源技术社团",
            "role": "技术负责人",
            "startTime": "2023-09-01",
            "endTime": "2024-06-30",
            "description": "组织每月技术分享，主讲 RAG 与向量检索入门，累计参与 300 余人次。",
        }
    ], ensure_ascii=False),
    "honors": json.dumps(["研究生学业奖学金一等奖", "校级优秀毕业生", "蓝桥杯省赛二等奖"],
                         ensure_ascii=False),
    "certificates": json.dumps(["英语六级（CET-6 562分）", "计算机技术与软件专业技术资格（中级）"],
                               ensure_ascii=False),
    "expect_position": "算法工程师",
    "expect_city": "北京",
    "expect_salary": "15-25K",
    "expect_industry": "国企/央企/互联网",
}


def connect():
    import pymysql
    return pymysql.connect(host="localhost", port=3306, user="root",
                           password="Root@123456", database="job_platform",
                           charset="utf8mb4")


def show(cur) -> None:
    cur.execute("SELECT * FROM resume")
    cols = [d[0] for d in cur.description]
    for row in cur.fetchall():
        d = dict(zip(cols, row))
        filled = {k: v for k, v in d.items() if v not in (None, "")}
        print(f"\n  user_id={d.get('user_id')} is_default={d.get('is_default')} "
              f"已填 {len(filled)}/{len(cols)} 字段")
        for k, v in filled.items():
            print(f"    {k:<22}: {str(v)[:120]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--show", action="store_true", help="只显示当前简历")
    args = ap.parse_args()

    conn = connect()
    cur = conn.cursor()

    if args.show:
        show(cur)
        conn.close()
        return 0

    print("=" * 78)
    print("写入前的简历状态")
    print("=" * 78)
    show(cur)

    if args.dry_run:
        print("\n  --dry-run：未写入")
        conn.close()
        return 0

    # ── 按 user_id 更新或插入，保证幂等 ──
    cur.execute("SELECT id FROM resume WHERE user_id=%s ORDER BY is_default DESC LIMIT 1",
                (TARGET_USER_ID,))
    row = cur.fetchone()

    fields = list(RESUME.keys())
    vals = [RESUME[f] for f in fields]

    if row:
        sets = ", ".join(f"`{f}`=%s" for f in fields)
        cur.execute(
            f"UPDATE resume SET {sets}, is_default=1, update_time=NOW() WHERE id=%s",
            vals + [row[0]],
        )
        action = f"更新既有简历 id={row[0]}"
    else:
        cols = ", ".join(f"`{f}`" for f in fields)
        ph = ", ".join(["%s"] * len(fields))
        cur.execute(
            f"INSERT INTO resume (user_id, {cols}, is_default, create_time, update_time) "
            f"VALUES (%s, {ph}, 1, NOW(), NOW())",
            [TARGET_USER_ID] + vals,
        )
        action = f"新建简历 id={cur.lastrowid}"

    conn.commit()
    print(f"\n  {action}（user_id={TARGET_USER_ID}，已填 {len(fields)} 个业务字段）")

    print()
    print("=" * 78)
    print("写入后")
    print("=" * 78)
    show(cur)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
