"""评测执行器：跑评测集 → 驱动 Agent → 采集运行数据 → 计算指标 → 出报告。

## 与原实现的区别

| 原实现 | 现在 |
|---|---|
| 串行逐条跑，无超时兜底 | 可配置并发 + 单条整体超时（`asyncio.wait_for`） |
| 把 `retrieved_docs`（doc_id）传给判官当上下文 | 传**正文**，忠实度判定才有效 |
| 只取 `correctness` 一个分 | 五项核心指标 + 检索 + 运行健康度 |
| `per_category` 恒为空 | 按 category / difficulty / intent 分组汇总 |
| 无 Bad Case 输出 | 自动挖掘 + 归因 + 写入回归集 |
| 指标算完就丢 | 结果 JSON 落盘，供基线比较与门禁 |

## 会话隔离

每条用例用全新的 `session_id`，配合 `MEMORY_BACKEND=memory`，
用例之间互不污染 —— 否则前一条的对话历史会通过短期记忆影响后一条，
评出来的就不是"单题能力"了。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# 必须在导入 app.* 之前设定：get_settings 是 lru_cache，晚设就不生效
os.environ.setdefault("MEMORY_BACKEND", "memory")

from benchmark.config import get_eval_settings  # noqa: E402

log = logging.getLogger("benchmark.evaluate")


# ══════════════════════════════════════════════════════════════════
# 数据集
# ══════════════════════════════════════════════════════════════════
def load_jsonl(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"数据集不存在：{p}")
    out = []
    with p.open(encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{p} 第 {i} 行不是合法 JSON：{exc}") from exc
    return out


def load_dataset(
    path: str | Path | None = None,
    *,
    include_extra: bool = True,
    limit: int | None = None,
    categories: list[str] | None = None,
) -> list[dict]:
    """加载评测集，可选合并补充集并按类别过滤。"""
    s = get_eval_settings()
    paths = [Path(path or s.dataset_file)]
    if include_extra and path is None:
        extra = Path(s.dataset_extra_file)
        if extra.exists():
            paths.append(extra)

    cases: list[dict] = []
    for p in paths:
        if p.exists():
            cases.extend(load_jsonl(p))

    # 按 id 去重（后加载的覆盖前者）
    dedup: dict[Any, dict] = {}
    for c in cases:
        dedup[c.get("id")] = c
    cases = list(dedup.values())

    if categories:
        keep = set(categories)
        cases = [c for c in cases if c.get("category") in keep]
    cases.sort(key=lambda c: (c.get("id") is None, c.get("id")))
    if limit:
        cases = cases[:limit]
    return cases


# ══════════════════════════════════════════════════════════════════
# 执行单条用例
# ══════════════════════════════════════════════════════════════════
async def run_case(case: dict, *, user_id: int = 1, timeout: int | None = None) -> dict:
    """跑一条用例，返回结构化运行结果（失败也返回结果，不抛异常）。"""
    from app.core.pipeline import AgentPipeline
    from app.db.session import get_sessionmaker

    s = get_eval_settings()
    timeout = timeout or s.case_timeout
    # 独立 session：用例之间不共享短期记忆
    session_id = f"eval-{case.get('id')}-{uuid.uuid4().hex[:8]}"
    maker = get_sessionmaker()
    t0 = time.perf_counter()

    try:
        async with maker() as session:
            # ── 多轮前置（setup）──
            # 先在**同一个 session_id** 下跑完前置轮次，让短期记忆里真的有上下文，
            # 再问评测问题。这样"指代消解 / 跨轮约束 / 记忆保持"才真正被测到。
            # 每轮用独立的 pipeline 实例：记忆是按 session_id 存在 store 里的，
            # 换实例不影响上下文；而统计/预算只统计**最终轮**，不会被前置轮污染。
            setup = case.get("setup") or []
            if setup:
                async def _preturn() -> None:
                    for turn in setup:
                        msg = turn.get("question") if isinstance(turn, dict) else str(turn)
                        if msg:
                            p = AgentPipeline(session)
                            await p.handle(user_id=user_id, message=msg,
                                           session_id=session_id)

                await asyncio.wait_for(_preturn(), timeout=timeout)
                t0 = time.perf_counter()   # 只统计最终轮延迟

            pipeline = AgentPipeline(session)
            result = await asyncio.wait_for(
                pipeline.handle(
                    user_id=user_id,
                    message=case["question"],
                    session_id=session_id,
                ),
                timeout=timeout,
            )
    except asyncio.TimeoutError:
        return {
            "id": case.get("id"), "session_id": session_id, "intent": "",
            "answer": "", "tool_calls": [], "retrieved_docs": [],
            "latency_ms": (time.perf_counter() - t0) * 1000,
            "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0,
            "error": f"TimeoutError: 超过 {timeout}s", "timed_out": True,
        }
    except Exception as exc:  # noqa: BLE001 - 单条失败不应中断整套评测
        log.warning("用例 #%s 执行异常：%s: %s", case.get("id"), type(exc).__name__, exc)
        return {
            "id": case.get("id"), "session_id": session_id, "intent": "",
            "answer": "", "tool_calls": [], "retrieved_docs": [],
            "latency_ms": (time.perf_counter() - t0) * 1000,
            "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0,
            "error": f"{type(exc).__name__}: {exc}", "timed_out": False,
        }

    stats = result.get("stats") or {}
    return {
        "id": case.get("id"),
        "session_id": session_id,
        "request_id": result.get("request_id"),
        "intent": result.get("intent") or "",
        "source": result.get("source") or "",
        "answer": result.get("reply") or "",
        # 工具调用：stats.tool_calls 已是工具名列表
        "tool_calls": list(stats.get("tool_calls") or []),
        # 检索结果：含 doc_id 与正文，裁判需要正文
        "retrieved_docs": list(stats.get("retrieved_docs") or []),
        "latency_ms": float(result.get("latency_ms") or (time.perf_counter() - t0) * 1000),
        "prompt_tokens": int(stats.get("prompt_tokens") or 0),
        "completion_tokens": int(stats.get("completion_tokens") or 0),
        "cost_usd": float(stats.get("cost_usd") or 0.0),
        "error": "",
        "timed_out": False,
    }


async def run_suite(
    cases: list[dict],
    *,
    user_id: int = 1,
    concurrency: int | None = None,
    progress=None,
) -> list[dict]:
    """并发跑完整套用例。"""
    s = get_eval_settings()
    sem = asyncio.Semaphore(max(1, concurrency or s.concurrency))
    total = len(cases)
    done = 0
    results: list[Optional[dict]] = [None] * total
    lock = asyncio.Lock()

    async def _worker(idx: int, case: dict):
        nonlocal done
        async with sem:
            r = await run_case(case, user_id=user_id)
        results[idx] = r
        async with lock:
            done += 1
            if progress:
                progress(done, total, case, r)

    await asyncio.gather(*[_worker(i, c) for i, c in enumerate(cases)])
    return [r for r in results if r is not None]


# ══════════════════════════════════════════════════════════════════
# 评测入口
# ══════════════════════════════════════════════════════════════════
RUNS_LATEST = "runs_latest.json"


def save_runs(runs: list[dict], path: str | Path | None = None) -> Path:
    """把「Agent 执行结果」单独落盘。

    为什么要单独存：执行阶段要花真金白银（被测模型调用）且耗时几十分钟，
    而裁判阶段可能因为额度、网络、提示词等问题需要反复重跑。
    两者解耦后，重跑裁判无需重新执行 Agent —— 这个设计实测省下了一整轮成本。
    """
    s = get_eval_settings()
    s.ensure_dirs()
    p = Path(path or (Path(s.reports_dir) / RUNS_LATEST))
    p.write_text(json.dumps({
        "saved_at": datetime.now().isoformat(),
        "total": len(runs),
        "ids": [r.get("id") for r in runs],
        "runs": runs,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def load_runs(path: str | Path | None = None) -> list[dict] | None:
    s = get_eval_settings()
    p = Path(path or (Path(s.reports_dir) / RUNS_LATEST))
    if not p.exists():
        return None
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
        return payload.get("runs") or []
    except Exception as exc:  # noqa: BLE001
        log.warning("复用执行结果失败：%s", exc)
        return None


def enrich_runs_from_trace(runs: list[dict]) -> int:
    """从 agent_trace 补回「工具输出」，返回补回的用例数。

    ## 为什么需要

    忠实度判定要拿"回答所依据的材料"核对每一句陈述。原先只收集了
    `search_knowledge` 的检索结果，于是**岗位推荐/简历优化类用例没有上下文**，
    忠实度被直接判 0（假阴性）—— 实测 75 题里有 39 题中招。

    ## 为什么能补

    工具输出其实**早已写进 agent_trace**（callback 的 `tool` 行），
    只是没进 runs。因此可以按 `request_id` 把它们捞回来，
    **无需重新执行 Agent**（省下一整轮真金白银与几十分钟）。
    """
    need = [r for r in runs if not r.get("tool_outputs") and r.get("request_id")]
    if not need:
        return 0
    try:
        import pymysql

        from app.config import get_settings

        a = get_settings()
        conn = pymysql.connect(
            host=a.mysql_host, port=a.mysql_port, user=a.mysql_user,
            password=a.mysql_password, database=a.mysql_db, charset="utf8mb4",
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("无法连接数据库补回工具输出：%s", exc)
        return 0

    filled = 0
    try:
        with conn.cursor() as cur:
            for r in need:
                cur.execute(
                    "SELECT output FROM agent_trace "
                    "WHERE request_id=%s AND node='tool' AND output IS NOT NULL "
                    "ORDER BY step",
                    (r["request_id"],),
                )
                outs = [row[0] for row in cur.fetchall() if row[0]]
                if outs:
                    r["tool_outputs"] = outs
                    filled += 1
    except Exception as exc:  # noqa: BLE001
        log.warning("补回工具输出时出错：%s", exc)
    finally:
        conn.close()
    return filled


async def evaluate_cases(
    cases: list[dict],
    *,
    user_id: int = 1,
    use_judge: bool = True,
    judge_samples: int | None = None,
    concurrency: int | None = None,
    progress=None,
    judge_progress=None,
    reuse_runs: bool = False,
):
    """跑用例并计算指标，返回 (results, summary, judge_stats, runs)。

    `reuse_runs=True` 时跳过 Agent 执行，直接复用上次落盘的执行结果
    （用于只调整了裁判参数/提示词后的重跑）。
    """
    from benchmark.judge import Judge
    from benchmark.metrics import Evaluator, summarize

    runs: list[dict] | None = None
    if reuse_runs:
        runs = load_runs()
        if runs:
            have = {r.get("id") for r in runs}
            need = {c.get("id") for c in cases}
            missing = need - have
            if missing:
                log.warning("复用的执行结果缺少 %d 条用例，将重新执行", len(missing))
                runs = None
            else:
                print(f"  已复用上次的执行结果（{len(runs)} 条），跳过 Agent 执行阶段")
        else:
            print("  未找到可复用的执行结果，将正常执行")

    if runs is None:
        runs = await run_suite(cases, user_id=user_id, concurrency=concurrency, progress=progress)
        try:
            p = save_runs(runs)
            print(f"  执行结果已保存：{p}")
            print("  （下次可用 --reuse-runs 跳过执行阶段，只重跑裁判）")
        except Exception as exc:  # noqa: BLE001
            log.warning("执行结果保存失败：%s", exc)

    # 补回工具输出：老版本执行结果没有 tool_outputs 字段，
    # 若不补，忠实度判定会因"缺少依据材料"而把大量用例误判为 0。
    try:
        n = enrich_runs_from_trace(runs)
        if n:
            print(f"  已从 Agent Trace 补回 {n} 条用例的工具输出（忠实度判定依据）")
    except Exception as exc:  # noqa: BLE001
        log.warning("补回工具输出失败（不影响其他指标）：%s", exc)

    runs_by_id = {r.get("id"): r for r in runs}

    judge = Judge(samples=judge_samples)
    ev = Evaluator(judge, use_judge=use_judge)
    results = []
    total = len(cases)
    for i, c in enumerate(cases, 1):
        results.append(await ev.evaluate_sample(c, runs_by_id.get(c.get("id"))))
        # 裁判阶段原本完全无输出，而它可能跑几十分钟，容易让人误以为卡死
        if judge_progress:
            judge_progress(i, total, results[-1], judge.stats)
        elif i % 5 == 0 or i == total:
            print(f"  评测中 [{i}/{total}] 裁判调用 {judge.stats['calls']} 次, "
                  f"缓存命中 {judge.stats['cache_hits']}, "
                  f"解析失败 {judge.stats['parse_failures']}, "
                  f"unknown {judge.stats['unknowns']}", flush=True)
    judge.flush()
    return results, summarize(results), judge.stats, runs


def save_results(results, summary: dict, runs: list[dict], *, tag: str = "") -> Path:
    s = get_eval_settings()
    s.ensure_dirs()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = Path(s.reports_dir) / f"eval_results_{tag + '_' if tag else ''}{stamp}.json"
    payload = {
        "generated_at": datetime.now().isoformat(),
        "judge_model": s.judge_model,
        "memory_backend": s.memory_backend,
        "summary": summary,
        "samples": [asdict(r) for r in results],
        "runs": runs,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


async def run_evaluation(
    dataset_path: str | None = None,
    run_tag: str = "run",
    limit: int | None = None,
    *,
    use_judge: bool = True,
) -> str:
    """向后兼容入口（API 路由 `/benchmark/run` 在用）。

    返回报告路径。
    """
    from benchmark.report import write_report

    cases = load_dataset(dataset_path, limit=limit)
    results, summary, judge_stats, runs = await evaluate_cases(
        cases, use_judge=use_judge
    )
    save_results(results, summary, runs, tag=run_tag)
    path = write_report(summary, results, tag=run_tag, judge_stats=judge_stats)
    return str(path)
