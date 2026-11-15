"""统一命令行入口。

    python -m benchmark.cli check                 # 环境与配置预检
    python -m benchmark.cli judge-test            # 裁判链路自检
    python -m benchmark.cli run --limit 10        # 小样本试跑
    python -m benchmark.cli run --all             # 全量
    python -m benchmark.cli report                # 从最近结果重新出报告
    python -m benchmark.cli mine                  # 挖掘 Bad Case 并更新回归集
    python -m benchmark.cli baseline              # 设为基线
    python -m benchmark.cli gate                  # 回归门禁
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# 评测必须走进程内记忆：必须在导入 app.* 之前设置
os.environ.setdefault("MEMORY_BACKEND", "memory")

# Windows 控制台默认 GBK(936)，若强制 UTF-8 输出，中文在 cmd 里会变成乱码；
# 而 .bat 文件本身是 GBK 编码，又要求控制台保持 936。
# 因此这里**不指定编码**（沿用系统默认），只把无法编码的字符替换掉，
# 避免因为打印一个符号（如 ✗）而抛 UnicodeEncodeError 中断整个评测。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass

from benchmark.config import get_eval_settings  # noqa: E402


def _setup(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _pct(v) -> str:
    return "—" if v is None else f"{v * 100:.1f}%"


def _print_summary(s: dict, judge_stats: dict | None = None) -> None:
    print()
    print("=" * 66)
    print("五项核心指标")
    print("=" * 66)
    print(f"  Route Accuracy（意图路由） : {_pct(s.get('route_accuracy'))}")
    print(f"  Tool Accuracy (F1)         : {s.get('tool_f1') if s.get('tool_f1') is not None else '—'}")
    print(f"  Tool Exact Match           : {_pct(s.get('tool_exact_match'))}")
    print(f"  Task Completion Rate       : {_pct(s.get('task_completion_rate'))}")
    print(f"  Faithfulness               : {_pct(s.get('faithfulness'))}")
    print(f"  Context Recall             : {_pct(s.get('context_recall'))}")
    print(f"  Context Relevance          : {_pct(s.get('context_relevance'))}")
    print()
    print("检索质量")
    print(f"  Recall@K {_pct(s.get('recall_at_k'))} | Hit@K {_pct(s.get('hit_at_k'))} "
          f"| 参与样本 {s.get('retrieval_evaluated', 0)}")
    print()
    print("对抗性")
    print(f"  样本 {s.get('adversarial_total', 0)} | "
          f"完成率 {_pct(s.get('adversarial_completion_rate'))}")
    print()
    print("运行健康度")
    print(f"  样本 {s.get('total')} | 错误率 {_pct(s.get('error_rate'))} | "
          f"超时率 {_pct(s.get('timeout_rate'))}")
    print(f"  延迟 P50 {s.get('latency_p50_ms')}ms | P90 {s.get('latency_p90_ms')}ms")
    print(f"  token 输入 {s.get('total_prompt_tokens', 0)} / "
          f"输出 {s.get('total_completion_tokens', 0)} | 成本 ${s.get('total_cost_usd', 0)}")
    print()
    print("裁判可靠性")
    print(f"  一致率 {s.get('judge_agreement_mean')} | unknown {s.get('judge_unknown_total')}")
    if judge_stats:
        print(f"  调用 {judge_stats.get('calls')} | 缓存命中 {judge_stats.get('cache_hits')} "
              f"| 解析失败 {judge_stats.get('parse_failures')}")
    print("=" * 66)


# ══════════════════════════════════════════════════════════════════
def cmd_check(args) -> int:
    _setup()
    s = get_eval_settings()
    ok = True
    print("=" * 66)
    print("环境预检")
    print("=" * 66)

    # 环境变量覆盖检查必须放在最前面。
    # 它发现的问题是"配置改对了却仍用旧值"，且**不会报错** ——
    # 实测后果是 200 条用例全部 401，而错误信息看起来像"key 失效"，
    # 排查方向很容易被带偏。
    from app.config import check_env_overrides

    overrides = check_env_overrides()
    if overrides:
        print("  [X] 检测到环境变量覆盖 .env（环境变量优先级更高！）:")
        for k, env_val, file_val in overrides:
            print(f"        {k}: 环境变量={env_val}  .env={file_val}")
        print("      → 这会让 .env 的改动完全不生效。请删除该环境变量后重开终端。")
        ok = False
    else:
        print("  配置来源     : .env（无环境变量覆盖）  OK")

    print(f"  短期记忆后端 : {s.memory_backend}  "
          f"({'OK（评测隔离）' if s.memory_backend == 'memory' else '注意：评测建议用 memory'})")
    print(f"  裁判模型     : {s.judge_model}")
    print(f"  裁判端点     : {s.judge_endpoint}")
    key_ok = bool(s.judge_api_key)
    print(f"  裁判 API Key : {'已配置' if key_ok else '缺失 [X]'}")
    ok &= key_ok

    for label, p in [
        ("评测集", s.dataset_file),
        ("补充集", s.dataset_extra_file),
        ("知识库", "data/knowledge.jsonl"),
        ("FAISS 索引", "data/faiss/index.faiss"),
    ]:
        exists = Path(p).exists()
        print(f"  {label:12s} : {'OK' if exists else '缺失'}  {p}")
        if label in ("评测集", "FAISS 索引"):
            ok &= exists

    print()
    print("  依赖：")
    import importlib.util as u
    for m in ("langgraph", "langchain_openai", "sqlalchemy", "asyncmy", "faiss", "redis"):
        found = u.find_spec(m) is not None
        print(f"    {'OK  ' if found else 'FAIL'} {m}")
        ok &= found

    print()
    print("  MySQL：")
    try:
        import pymysql
        conn = pymysql.connect(host="127.0.0.1", port=3306, user="root",
                               password="Root@123456", database="job_agent",
                               connect_timeout=3)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM agent_trace")
        print(f"    OK（agent_trace 现有 {cur.fetchone()[0]} 行）")
        conn.close()
    except Exception as e:  # noqa: BLE001
        print(f"    FAIL：{type(e).__name__}: {e}")
        ok = False

    print()
    print("  Ollama（embedding 用）：")
    try:
        import requests
        r = requests.get("http://127.0.0.1:11434/api/tags", timeout=5)
        models = [m["name"] for m in r.json().get("models", [])]
        hit = any("qwen3-embedding" in m for m in models)
        print(f"    {'OK' if hit else '缺 qwen3-embedding:4b'}  已拉取 {len(models)} 个模型")
        ok &= hit
    except Exception as e:  # noqa: BLE001
        print(f"    FAIL：{type(e).__name__}")
        ok = False

    print()
    print("预检结果：", "通过" if ok else "存在问题（见上）")
    return 0 if ok else 1


def cmd_judge_test(args) -> int:
    _setup()
    from benchmark.judge import self_test
    return asyncio.run(self_test())


def cmd_run(args) -> int:
    _setup(args.verbose)
    from benchmark.badcase import mine, save_badcases, summarize_causes, update_regression_set
    from benchmark.evaluate import evaluate_cases, load_dataset, save_results
    from benchmark.metrics import by_group
    from benchmark.report import write_report

    cases = load_dataset(
        limit=None if args.all else args.limit,
        categories=args.categories.split(",") if args.categories else None,
    )
    if not cases:
        print("评测集为空")
        return 1

    from collections import Counter
    cats = Counter(c.get("category", "?") for c in cases)
    intents = Counter(c.get("expected_intent", "?") for c in cases)
    print(f"评测集：{len(cases)} 条")
    print("  类别：", ", ".join(f"{k}={v}" for k, v in sorted(cats.items())))
    print("  意图：", ", ".join(f"{k}={v}" for k, v in sorted(intents.items())))
    print(f"  裁判：{'关闭' if args.no_judge else get_eval_settings().judge_model}")

    def progress(i, total, case, run):
        flag = "!" if run.get("error") else " "
        print(f"  [{i}/{total}]{flag} #{case.get('id')} "
              f"{str(case.get('question'))[:34]}  "
              f"intent={run.get('intent') or '-'} "
              f"{run.get('latency_ms', 0):.0f}ms", flush=True)

    # 裁判阶段进度：过去这里完全没有输出，而裁判可能跑几十分钟，
    # 用户会以为卡死（此前的 token 预算不足导致整轮失败时也毫无提示）
    _fail_seen = {"n": 0}

    def judge_progress(i, total, res, stats):
        fails = stats.get("parse_failures", 0)
        if i % 5 == 0 or i == total or fails > _fail_seen["n"]:
            _fail_seen["n"] = fails
            extra = (f", token 加倍重试 {stats.get('token_escalations', 0)}"
                     if stats.get("token_escalations") else "")
            print(f"  评测中 [{i}/{total}] 裁判调用 {stats.get('calls', 0)} 次, "
                  f"缓存命中 {stats.get('cache_hits', 0)}, "
                  f"解析失败 {fails}, unknown {stats.get('unknowns', 0)}{extra}",
                  flush=True)

    results, summary, judge_stats, runs = asyncio.run(
        evaluate_cases(
            cases,
            use_judge=not args.no_judge,
            judge_samples=args.judge_samples or None,
            concurrency=args.concurrency or None,
            progress=progress,
            judge_progress=None if args.no_judge else judge_progress,
            reuse_runs=args.reuse_runs,
        )
    )

    from benchmark.report import load_latest_results
    prev = load_latest_results()
    baseline = (prev or {}).get("summary")

    cat_groups = by_group(results, lambda r: r.category)
    intent_groups = by_group(results, lambda r: r.expected_intent)

    res_path = save_results(results, summary, runs, tag=args.tag)
    rep_path = write_report(
        summary, results, baseline=baseline, judge_stats=judge_stats,
        category_groups=cat_groups, intent_groups=intent_groups, tag=args.tag,
    )
    _print_summary(summary, judge_stats)

    # Bad Case
    cases_by_id = {c.get("id"): c for c in cases}
    bc = mine(results, cases_by_id)
    if bc:
        bc_path = save_badcases(bc, tag=args.tag)
        reg_path, added, total = update_regression_set(bc)
        print(f"\nBad Case：{len(bc)} 条 → {bc_path}")
        print(f"  归因分布：{summarize_causes(bc)}")
        print(f"  回归集：新增 {added}，累计 {total} → {reg_path}")

    print(f"\n结果 JSON：{res_path}")
    print(f"报告     ：{rep_path}")
    return 0


def cmd_report(args) -> int:
    _setup()
    from benchmark.metrics import SampleResult, by_group
    from benchmark.report import load_latest_results, write_report

    payload = load_latest_results()
    if not payload:
        print("找不到历史结果 JSON，请先运行 run")
        return 1
    results = [SampleResult(**s) for s in payload.get("samples", [])]
    summary = payload.get("summary", {})
    path = write_report(
        summary, results,
        category_groups=by_group(results, lambda r: r.category),
        intent_groups=by_group(results, lambda r: r.expected_intent),
        tag=args.tag or "regen",
    )
    _print_summary(summary)
    print(f"\n报告已重新生成：{path}")
    return 0


def cmd_mine(args) -> int:
    _setup()
    from benchmark.badcase import mine, save_badcases, summarize_causes, update_regression_set
    from benchmark.evaluate import load_dataset
    from benchmark.metrics import SampleResult
    from benchmark.report import load_latest_results

    payload = load_latest_results()
    if not payload:
        print("找不到历史结果 JSON，请先运行 run")
        return 1
    results = [SampleResult(**s) for s in payload.get("samples", [])]
    cases_by_id = {c.get("id"): c for c in load_dataset(include_extra=True)}

    bc = mine(results, cases_by_id)
    if not bc:
        print("没有挖掘到 Bad Case")
        return 0
    p1 = save_badcases(bc, tag=args.tag or "mine")
    p2, added, total = update_regression_set(bc)
    print(f"Bad Case {len(bc)} 条 → {p1}")
    print("归因分布：", summarize_causes(bc))
    print(f"回归集：新增 {added}，累计 {total} → {p2}")
    return 0


def cmd_baseline(args) -> int:
    _setup()
    from benchmark.regression import set_baseline
    return set_baseline()


def cmd_gate(args) -> int:
    _setup()
    from benchmark.regression import gate
    return gate(args.tolerance)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m benchmark.cli",
        description="求职 Agent 自动化评测（LLM-as-Judge + Agent Trace）",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check", help="环境与配置预检").set_defaults(func=cmd_check)
    sub.add_parser("judge-test", help="裁判链路自检").set_defaults(func=cmd_judge_test)

    sp = sub.add_parser("run", help="执行评测")
    sp.add_argument("--all", action="store_true", help="跑全部样本")
    sp.add_argument("--limit", type=int, default=10, help="样本上限（未指定 --all 时生效）")
    sp.add_argument("--categories", default="", help="只跑指定类别，逗号分隔")
    sp.add_argument("--no-judge", action="store_true", help="跳过裁判（只算路由/工具/检索）")
    sp.add_argument("--judge-samples", type=int, default=0, help="裁判自一致性采样次数")
    sp.add_argument("--concurrency", type=int, default=0, help="并发数")
    sp.add_argument("--reuse-runs", action="store_true",
                    help="复用上次的 Agent 执行结果，跳过执行阶段只重跑裁判（省时省钱）")
    sp.add_argument("--tag", default="", help="批次名")
    sp.add_argument("--verbose", action="store_true")
    sp.set_defaults(func=cmd_run)

    sp = sub.add_parser("report", help="从最近结果重新出报告")
    sp.add_argument("--tag", default="")
    sp.set_defaults(func=cmd_report)

    sp = sub.add_parser("mine", help="挖掘 Bad Case 并更新回归集")
    sp.add_argument("--tag", default="")
    sp.set_defaults(func=cmd_mine)

    sub.add_parser("baseline", help="把最近一次结果设为基线").set_defaults(func=cmd_baseline)

    sp = sub.add_parser("gate", help="回归门禁")
    sp.add_argument("--tolerance", type=float, default=0.02)
    sp.set_defaults(func=cmd_gate)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
