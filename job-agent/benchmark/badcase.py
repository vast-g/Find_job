"""Bad Case 自动挖掘、归因与回归集维护。

对应简历里的「结合 Bad Case 回归优化」。

不同原因要用完全不同的修法，混在一起优化是无效劳动，因此按 7 类归因：

| 原因 | 含义 | 典型修法 |
|------|------|----------|
| `runtime_failure` | 执行报错 | 修容错、调超时 |
| `case_timeout` | 单条超时 | 查工具耗时、调 timeout |
| `route_misclassification` | 意图识别错 | 改 INTENT_PROMPT、补 few-shot |
| `tool_selection` | 工具选错/漏调/多调 | 改工具描述或 system prompt，或检查白名单 |
| `retrieval_miss` | 检索没召回 | 扩知识库、调 chunk/top_k、改 query rewrite |
| `hallucination_suspected` | 回答含上下文不支持的陈述 | 加反幻觉约束、强化引用 |
| `adversarial_failure` | 对抗样本被带偏（逢迎） | 补对抗样例、加强澄清指令 |
| `task_incomplete` | 答了但没答到点上 | 改 prompt / 补知识库 |

回归集按 `question + cause` 去重累积，供 `gate` 做门禁：
**任何改动都不允许让历史错过的样本重新出错。**
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterable, Optional

from benchmark.config import get_eval_settings


def classify_causes(r) -> list[tuple[str, str, str]]:
    """归因，返回 [(原因, 严重度, 证据)]。"""
    s = get_eval_settings()
    out: list[tuple[str, str, str]] = []

    if r.error:
        cause = "case_timeout" if getattr(r, "timed_out", False) else "runtime_failure"
        out.append((cause, "blocker", r.error[:200]))

    if r.route_ok is False:
        out.append(("route_misclassification", "high",
                    f"期望 {r.expected_intent} 实得 {r.predicted_intent}"))
    if r.tool_f1 is not None and r.tool_f1 < 0.999:
        out.append(("tool_selection", "high",
                    f"期望 {r.golden_tools} 实得 {r.called_tools} (F1={r.tool_f1})"))
    if r.recall_at_k is not None and r.recall_at_k < 0.999:
        out.append(("retrieval_miss", "high",
                    f"Recall@K={r.recall_at_k}（期望 {r.ground_truth_docs}，"
                    f"实得 {r.retrieved_docs[:5]}）"))
    if r.faithfulness is not None and r.faithfulness < s.faithfulness_floor:
        out.append(("hallucination_suspected", "blocker",
                    f"Faithfulness={r.faithfulness}"))
    if r.adversarial and r.task_completion is False:
        out.append(("adversarial_failure", "blocker",
                    "对抗样本未通过：可能未识别用户错误前提"))
    if r.task_completion is False and not r.adversarial:
        out.append(("task_incomplete", "high", "验收标准判定为 fail"))
    return out


def mine(results: Iterable, cases_by_id: Optional[dict] = None) -> list[dict]:
    cases_by_id = cases_by_id or {}
    found: list[dict] = []
    for r in results:
        causes = classify_causes(r)
        if not causes:
            continue
        case = cases_by_id.get(r.id, {})
        for cause, severity, evidence in causes:
            found.append({
                "id": r.id,
                "category": r.category,
                "question": r.question,
                "cause": cause,
                "severity": severity,
                "evidence": evidence,
                "expected_intent": r.expected_intent,
                "predicted_intent": r.predicted_intent,
                "golden_tools": r.golden_tools,
                "called_tools": r.called_tools,
                "ground_truth_docs": r.ground_truth_docs,
                "retrieved_docs": r.retrieved_docs[:8],
                "faithfulness": r.faithfulness,
                "context_recall": r.context_recall,
                "task_completion": r.task_completion,
                "latency_ms": r.latency_ms,
                "answer": (r.answer or "")[:400],
                # 回归集需要的原始字段
                "regression_entry": {
                    k: case.get(k) for k in (
                        "id", "category", "question", "expected_intent",
                        "golden_tools", "ground_truth_docs", "expected",
                        "adversarial", "difficulty", "success_criteria",
                    ) if case.get(k) is not None
                },
            })
    order = {"blocker": 0, "high": 1, "medium": 2, "low": 3}
    found.sort(key=lambda x: (order.get(x["severity"], 9), x["id"]))
    return found


def save_badcases(cases: list[dict], tag: str = "") -> Path:
    s = get_eval_settings()
    Path(s.badcases_dir).mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    path = Path(s.badcases_dir) / f"badcases_{tag + '_' if tag else ''}{stamp}.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for c in cases:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")
    return path


def update_regression_set(cases: list[dict], path: Optional[Path] = None) -> tuple[Path, int, int]:
    """按 question + cause 去重，追加进回归集。返回 (路径, 新增, 总数)。"""
    s = get_eval_settings()
    p = Path(path or s.regression_file)
    p.parent.mkdir(parents=True, exist_ok=True)

    existing: dict[str, dict] = {}
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            existing[f"{obj.get('question')}||{obj.get('_cause', '')}"] = obj

    added = 0
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    for c in cases:
        entry = dict(c.get("regression_entry") or {})
        if not entry.get("question"):
            continue
        entry["_cause"] = c["cause"]
        entry["_severity"] = c["severity"]
        entry["_first_seen"] = now
        entry["_evidence"] = c["evidence"]
        entry["reviewed"] = False
        key = f"{entry['question']}||{c['cause']}"
        if key in existing:
            existing[key]["_last_seen"] = now
            existing[key]["_evidence"] = c["evidence"]
            continue
        existing[key] = entry
        added += 1

    with p.open("w", encoding="utf-8") as fh:
        for obj in existing.values():
            fh.write(json.dumps(obj, ensure_ascii=False) + "\n")
    return p, added, len(existing)


def summarize_causes(cases: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for c in cases:
        counts[c["cause"]] = counts.get(c["cause"], 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


__all__ = [
    "classify_causes", "mine", "save_badcases",
    "update_regression_set", "summarize_causes",
]
