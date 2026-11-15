"""评测报告生成（Markdown + 机器可读 JSON）。

报告刻意包含「裁判可靠性」与「评测条件」两节：
读者必须能判断 0.85 的 Faithfulness 是真信号还是裁判噪声，
以及这组数字在什么前提下成立的。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

from benchmark.config import get_eval_settings


def _pct(v: Optional[float]) -> str:
    return "—" if v is None else f"{v * 100:.1f}%"


def _num(v: Optional[float], d: int = 3) -> str:
    return "—" if v is None else f"{v:.{d}f}"


def _delta(cur: Optional[float], base: Optional[float]) -> str:
    if cur is None or base is None:
        return "—"
    d = cur - base
    if abs(d) < 1e-9:
        return "±0"
    return f"{'▲' if d > 0 else '▼'}{abs(d) * 100:.1f}pp"


def build_markdown(
    summary: dict[str, Any],
    results: list[Any],
    *,
    baseline: Optional[dict] = None,
    judge_stats: Optional[dict] = None,
    category_groups: Optional[dict] = None,
    intent_groups: Optional[dict] = None,
    tag: str = "",
) -> str:
    s = summary
    s_conf = get_eval_settings()
    L: list[str] = []

    L.append("# 求职 Agent 评测报告")
    if tag:
        L.append(f"> 评测批次：`{tag}`")
    L.append("")
    L.append(f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}")
    # 被测模型名从配置读取，不写死 —— 写死会在换模型/换渠道后变成误导信息
    # （曾写死 "deepseek-v4.1-flash（百炼）"，而后来已整体迁到 DeepSeek 官方 API）。
    try:
        from app.config import get_settings as _app_settings

        _a = _app_settings()
        _host = (_a.openai_base_url or "").rstrip("/").split("//")[-1].split("/")[0]
        L.append(f"- 被测 Agent：`{_a.llm_model}`（{_host}，ReAct + RAG）")
    except Exception:  # noqa: BLE001
        L.append("- 被测 Agent：`(未读取到配置)`（ReAct + RAG）")
    L.append(f"- 裁判模型：`{s_conf.judge_model}`（与被测模型**相互独立**）")
    L.append(f"- 短期记忆后端：`{s_conf.memory_backend}`（评测用进程内存储，用例间隔离）")
    L.append(f"- 样本总数：{s.get('total', 0)}")
    L.append("")

    # ── 一、五项核心指标 ──
    L.append("## 一、五项核心指标")
    L.append("")
    L.append("| 指标 | 本次 | 基线 | 变化 | 说明 |")
    L.append("|------|:----:|:----:|:----:|------|")
    for label, key, desc in [
        ("Route Accuracy（意图路由）", "route_accuracy", "意图识别是否正确（确定性断言）"),
        ("Tool Accuracy (F1)", "tool_f1", "工具调用集合的 P/R 调和平均"),
        ("Tool Exact Match", "tool_exact_match", "工具调用集合与期望完全一致的比例"),
        ("Task Completion Rate", "task_completion_rate", "按验收标准判定任务完成"),
        ("Faithfulness", "faithfulness", "回答原子陈述被检索上下文支持的比例"),
        ("Context Recall", "context_recall", "标准答案要点能在上下文中找到支撑的比例"),
        ("Context Relevance", "context_relevance", "召回片段与问题相关的比例"),
    ]:
        cur, base = s.get(key), (baseline or {}).get(key)
        L.append(f"| {label} | {_pct(cur)} | {_pct(base)} | {_delta(cur, base)} | {desc} |")
    L.append("")

    ev = s.get("evaluated", {})
    L.append(
        f"> 参与计算的样本数：Faithfulness {ev.get('faithfulness', 0)} / "
        f"Context Recall {ev.get('context_recall', 0)} / "
        f"Task Completion {ev.get('task_completion', 0)}。"
        "未参与的是无标准答案要点的条目 —— **没有参考答案就不给 recall 分数**。"
    )
    L.append("")

    # ── 二、检索质量 ──
    L.append("## 二、检索质量（RAG）")
    L.append("")
    L.append("| 指标 | 值 |")
    L.append("|------|:--:|")
    L.append(f"| Recall@K | {_pct(s.get('recall_at_k'))} |")
    L.append(f"| Hit@K | {_pct(s.get('hit_at_k'))} |")
    L.append(f"| 参与检索评测的样本 | {s.get('retrieval_evaluated', 0)} |")
    L.append("")
    if s.get("retrieval_evaluated", 0) == 0:
        L.append("> ⚠️ 本批次**没有样本参与检索评测**（`ground_truth_docs` 全为空），"
                 "Recall/MRR 无意义。")
        L.append("")

    # ── 三、对抗性专项 ──
    L.append("## 三、对抗性专项目标")
    L.append("")
    L.append(f"- 对抗样本数：{s.get('adversarial_total', 0)}")
    L.append(f"- 对抗样本完成率：{_pct(s.get('adversarial_completion_rate'))}")
    L.append("")
    L.append("> 对抗样本考察 Agent 是否识别并纠正用户的**错误前提/超范围诉求**，"
             "而不是逢迎附和。这是求职类 Agent 最容易被忽视的风险点。")
    L.append("")

    # ── 四、运行健康度 ──
    L.append("## 四、运行健康度与成本")
    L.append("")
    L.append("| 指标 | 值 |")
    L.append("|------|:--:|")
    L.append(f"| 错误率 | {_pct(s.get('error_rate'))} |")
    L.append(f"| 超时率 | {_pct(s.get('timeout_rate'))} |")
    L.append(f"| 延迟 P50 | {_num(s.get('latency_p50_ms'), 0)} ms |")
    L.append(f"| 延迟 P90 | {_num(s.get('latency_p90_ms'), 0)} ms |")
    L.append(f"| 延迟均值 | {_num(s.get('latency_mean_ms'), 0)} ms |")
    L.append(f"| 总 token | 输入 {s.get('total_prompt_tokens', 0)} / "
             f"输出 {s.get('total_completion_tokens', 0)} |")
    L.append(f"| 总成本 | ${s.get('total_cost_usd', 0)} |")
    L.append("")

    # ── 五、裁判可靠性 ──
    L.append("## 五、裁判可靠性（评测自身的置信度）")
    L.append("")
    L.append("| 指标 | 值 |")
    L.append("|------|:--:|")
    L.append(f"| 判定一致率均值 | {_num(s.get('judge_agreement_mean'))} |")
    L.append(f"| unknown 判定总数 | {s.get('judge_unknown_total', 0)} |")
    L.append(f"| 完成度无法判定的样本 | {s.get('samples_with_unknown_completion', 0)} |")
    if judge_stats:
        L.append(f"| 裁判调用次数 | {judge_stats.get('calls', 0)} |")
        L.append(f"| 缓存命中 | {judge_stats.get('cache_hits', 0)} |")
        L.append(f"| JSON 解析失败 | {judge_stats.get('parse_failures', 0)} |")
    L.append("")
    L.append("> `unknown` 是**有效输出**：裁判判不了就如实记录。"
             "原实现把解析失败折算成 0 分，等于把「判不了」当成「答错了」，"
             "会系统性拉低分数且不可见。")
    L.append("")

    # ── 六、分类别 / 分意图 ──
    if category_groups:
        L.append("## 六、按类别拆解")
        L.append("")
        L.append("| 类别 | 样本 | Route Acc | Tool F1 | Task Completion | Faithfulness |")
        L.append("|------|:----:|:---------:|:-------:|:---------------:|:------------:|")
        for k, g in category_groups.items():
            L.append(f"| {k} | {g.get('total', 0)} | {_pct(g.get('route_accuracy'))} | "
                     f"{_num(g.get('tool_f1'))} | {_pct(g.get('task_completion_rate'))} | "
                     f"{_pct(g.get('faithfulness'))} |")
        L.append("")

    if intent_groups:
        L.append("## 七、按意图拆解")
        L.append("")
        L.append("| 期望意图 | 样本 | Route Acc | Tool F1 | Task Completion |")
        L.append("|----------|:----:|:---------:|:-------:|:---------------:|")
        for k, g in intent_groups.items():
            L.append(f"| {k} | {g.get('total', 0)} | {_pct(g.get('route_accuracy'))} | "
                     f"{_num(g.get('tool_f1'))} | {_pct(g.get('task_completion_rate'))} |")
        L.append("")

    # ── 八、失败样本 ──
    fails = [r for r in results
             if (r.route_ok is False) or (r.task_completion is False) or r.error]
    L.append("## 八、失败样本（最多 20 条）")
    L.append("")
    if not fails:
        L.append("本批次没有路由错误、任务未完成或运行错误的样本。")
    else:
        L.append("| # | 类别 | 问题 | 期望意图 | 实际意图 | 期望工具 | 实调工具 | 完成度 |")
        L.append("|---|------|------|----------|----------|----------|----------|:------:|")
        for r in fails[:20]:
            q = (r.question or "")[:34].replace("|", "/")
            rd = "✓" if r.route_ok else "✗"
            tc = {True: "pass", False: "fail", None: "?"}.get(r.task_completion, "?")
            L.append(f"| {r.id} | {r.category} | {q} | {r.expected_intent} | "
                     f"{r.predicted_intent} {rd} | {','.join(r.golden_tools) or '—'} | "
                     f"{','.join(r.called_tools) or '—'} | {tc} |")
    L.append("")

    # ── 九、口径说明 ──
    L.append("## 九、口径与前提说明")
    L.append("")
    L.append("- **路由与工具不用裁判**：意图是分类输出、工具是集合比较，都有精确解，"
             "交给 LLM 打分只会引入噪声。")
    L.append("- **含有参考答案要点的样本才有 Context Recall**，其余不参与该项。")
    L.append("- **doc_id 按前缀匹配**：索引里是 `doc_xxx#0`（含分块序号），"
             "数据集只写到源文档 `doc_xxx`，比对时取 `#` 前部分。")
    L.append("- **评测隔离**：每条用例独立 `session_id` + 进程内记忆后端，"
             "用例之间不共享短期记忆。")
    # 索引规模动态读取：写死会在语料变更后变成过期描述（曾经写死"18 个片段"，
    # 而实际索引已扩到 1.4 万片段，报告里的前提说明就自相矛盾了）。
    idx_note = ""
    try:
        from app.config import get_settings as _gs

        docs_path = Path(_gs().faiss_index_dir) / "documents.jsonl"
        if docs_path.exists():
            n = sum(1 for line in docs_path.read_text(encoding="utf-8").split("\n")
                    if line.strip())
            idx_note = f"**当前索引规模 {n} 个片段**"
    except Exception:  # noqa: BLE001
        idx_note = "索引规模未读取到"
    L.append(f"- **检索前提**：{idx_note}。历史报告中的 Recall@K / Context Recall "
             "**不可跨语料版本直接比较** —— 语料、分块大小或 BM25 分词方式一变，"
             "这些指标会整体位移。")
    L.append("")
    return "\n".join(L)


def write_report(
    summary: dict[str, Any],
    results: list[Any],
    *,
    baseline: Optional[dict] = None,
    judge_stats: Optional[dict] = None,
    category_groups: Optional[dict] = None,
    intent_groups: Optional[dict] = None,
    tag: str = "",
) -> Path:
    s = get_eval_settings()
    s.ensure_dirs()
    md = build_markdown(
        summary, results, baseline=baseline, judge_stats=judge_stats,
        category_groups=category_groups, intent_groups=intent_groups, tag=tag,
    )
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out = Path(s.reports_dir) / f"eval_report_{tag + '_' if tag else ''}{stamp}.md"
    out.write_text(md, encoding="utf-8")

    # 同时更新 latest_{tag}.json，供人工查看与 regression 参考。
    # 「重新渲染」不是一次新的评测，不能覆盖 latest 标记，否则基线对比会被
    # 一次 report 操作污染（踩过：regen 用 5 条样本的结果覆盖了 75 条的 latest）。
    if tag != "regen":
        latest = Path(s.reports_dir) / f"latest_{tag}.json"
        latest.write_text(
            json.dumps({"summary": summary, "tag": tag,
                        "time": time.strftime("%Y-%m-%d %H:%M:%S")},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return out


def load_latest_results() -> Optional[dict]:
    """读取最近一次 eval_results_*.json。

    ⚠️ 必须按**修改时间**取最新，不能按文件名排序：
    带 tag 的文件名形如 `eval_results_ds_peritem_20261004_205045.json`，
    而字典序里字母排在数字之后，于是"按名字排序取最后一个"会取到带 tag 的旧文件，
    把真正的全量结果忽略掉（实测踩过这个坑：95 条样本的报告被 5 条样本的结果覆盖）。
    """
    s = get_eval_settings()
    files = [p for p in Path(s.reports_dir).glob("eval_results_*.json") if p.is_file()]
    if not files:
        return None
    newest = max(files, key=lambda p: p.stat().st_mtime)
    try:
        return json.loads(newest.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


__all__ = ["build_markdown", "write_report", "load_latest_results"]
