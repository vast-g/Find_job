"""工具：search_jobs 岗位检索。

## 改造记录（评测暴露的问题）

1. **静默降级**：原实现 `except Exception:` 直接回退到硬编码的 2 条岗位，
   **既不记日志也不计数**。后果是评测报告里"岗位召回为空"永远分不清是
   「库里确实没有」还是「后端挂了/没启动」—— 而实际上当时的 `localhost:8080`
   后端根本没运行，75 条用例里有 20 条岗位推荐全部走的是那 2 条假数据。
   现在：回退必打 WARNING，并计入可读的调用统计。

2. **`salary_range` 是死参数**：签名里有，但函数体从未使用，
   模型传了薪资区间也完全不起作用（静默忽略，与 BM25 的
   `preprocessor`/`preprocess_func` 是同一类坑）。现在真正参与过滤。

3. **超时过短**：原为 5 秒。岗位接口带多表 join + 模糊匹配，
   高峰期容易超时并触发降级。放宽到 10 秒。

4. **空结果与故障不可区分**：现在分别计数（`backend_empty` / `fallback`），
   评测可直接算"降级率"。
"""
from __future__ import annotations

import logging
import re

import httpx
from langchain_core.tools import tool

from app.tools.registry import register_tool

log = logging.getLogger("app.tools.job_tools")

JOB_API_BASE = "http://localhost:8080"   # Java 后端（job-platform），需保持运行

# 后端不可用时的兜底数据。**仅用于让流程不崩**，不代表真实岗位库。
_JOBS = [
    {"title": "算法工程师", "company": "中国银行", "city": "北京", "salary": "15-25k", "tags": "国企,校招"},
    {"title": "软件开发工程师", "company": "国家电网", "city": "上海", "salary": "12-20k", "tags": "央企,本科"},
]

# 调用统计：评测与排障用。回退率长期 > 0 说明后端没起来。
CALL_STATS = {"total": 0, "ok": 0, "backend_empty": 0, "fallback": 0, "error": 0}


def reset_call_stats() -> None:
    for k in CALL_STATS:
        CALL_STATS[k] = 0


def get_call_stats() -> dict:
    return dict(CALL_STATS)


_SALARY_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[kK千]?")


def _parse_salary(text: str) -> tuple[float, float] | None:
    """把 "10-20k" / "8000-15000" / "15k" 解析成 (min, max)，单位统一为元。"""
    if not text:
        return None
    nums = []
    for m in _SALARY_RE.finditer(str(text)):
        val = float(m.group(1))
        # 带 k/K/千 的按千元换算
        seg = m.group(0).lower()
        if "k" in seg or "千" in seg or val <= 100:   # 15 → 15k；15000 不换算
            val *= 1000
        nums.append(val)
    if not nums:
        return None
    return (min(nums), max(nums)) if len(nums) > 1 else (nums[0], nums[0])


def _job_salary_bounds(job: dict) -> tuple[float, float] | None:
    """从岗位记录里取出薪资区间（后端返回 salaryMin/salaryMax，兜底数据是 'salary' 字符串）。"""
    lo = job.get("salaryMin") or job.get("salary_min")
    hi = job.get("salaryMax") or job.get("salary_max")
    if lo or hi:
        try:
            return float(lo or 0), float(hi or 0)
        except (TypeError, ValueError):
            pass
    return _parse_salary(job.get("salary") or "")


def _apply_salary_filter(jobs: list[dict], salary_range: str | None) -> list[dict]:
    """按薪资区间过滤。区间不合法或岗位无薪资信息时**保留**该岗位（宁多勿漏）。"""
    want = _parse_salary(salary_range) if salary_range else None
    if not want:
        return jobs
    lo, hi = want
    out = []
    for j in jobs:
        got = _job_salary_bounds(j)
        if not got:
            out.append(j)            # 无薪资信息，保留
            continue
        jlo, jhi = got
        if jhi <= 0 and jlo <= 0:
            out.append(j)            # 薪资未公开，保留
            continue
        # 区间有交集即视为匹配
        if jhi >= lo and (jlo <= hi or jlo == 0):
            out.append(j)
    return out


@tool
async def search_jobs(keywords: str, city: str | None = None,
                      salary_range: str | None = None) -> list[dict]:
    """按关键词/城市/薪资检索岗位。用于岗位推荐，输入岗位关键词。"""
    CALL_STATS["total"] += 1
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            params: dict[str, object] = {"keyword": keywords}
            if city:
                params["city"] = city
            r = await c.get(f"{JOB_API_BASE}/user/job/list", params=params)
            r.raise_for_status()
            data = r.json().get("data") or []
            if data:
                CALL_STATS["ok"] += 1
            else:
                CALL_STATS["backend_empty"] += 1
                log.info("岗位检索无结果：keyword=%r city=%r", keywords, city)
            return _apply_salary_filter(data, salary_range)
    except Exception as exc:  # noqa: BLE001
        # 降级必须可见：否则评测无法区分"库里没有"与"后端挂了"
        CALL_STATS["fallback"] += 1
        CALL_STATS["error"] += 1
        log.warning("岗位后端不可达，回退静态兜底数据（仅 %d 条）：%s: %s",
                    len(_JOBS), type(exc).__name__, exc)
        fallback = [j for j in _JOBS
                    if keywords in j["title"] or (city and city in j["city"])]
        return _apply_salary_filter(fallback, salary_range)


register_tool(search_jobs)
