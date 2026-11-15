"""离线管线自测：不调用任何模型，验证「指标 → 报告 → Bad Case → 回归集」链路。

用途：
  * 改完评测代码后秒级回归，不必等 75 条用例跑完；
  * CI 冒烟。

    python tools/selftest_pipeline.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.stdout.reconfigure(errors="replace")

from benchmark.badcase import mine, summarize_causes, update_regression_set  # noqa: E402
from benchmark.metrics import (  # noqa: E402
    SampleResult, by_group, doc_base, match_docs, summarize, tool_scores,
)
from benchmark.report import build_markdown  # noqa: E402

FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    if not cond:
        FAIL.append(name)


print("=" * 66)
print("1) 工具集合评分")
print("=" * 66)
check("完全匹配", tool_scores(["a"], ["a"])[:3] == (1.0, 1.0, 1.0))
check("空期望空预测 = 正确", tool_scores([], [])[3] is True)
check("漏调 → recall=0.5", tool_scores(["a", "b"], ["a"])[1] == 0.5)
check("多调 → precision=0.5", tool_scores(["a"], ["a", "b"])[0] == 0.5)
check("误调用（期望空）→ precision=0", tool_scores([], ["a"])[0] == 0.0)

print()
print("=" * 66)
print("2) doc_id 前缀匹配（索引含分块序号，标注只到源文档）")
print("=" * 66)
check("doc_base 去分块序号", doc_base("doc_interview_flow#3") == "doc_interview_flow")
check("命中同文档其它分块", match_docs(["doc_x#1"], ["doc_x"]) == {"doc_x"})
check("未命中", match_docs(["doc_y#0"], ["doc_x"]) == set())
check("部分命中", match_docs(["doc_x#0", "doc_z#0"], ["doc_x", "doc_y"]) == {"doc_x"})

print()
print("=" * 66)
print("3) 指标汇总")
print("=" * 66)
results = [
    # 全对，且检索命中
    SampleResult(1, "面试问答", "国企面试流程", expected_intent="qa", predicted_intent="qa",
                 route_ok=True, golden_tools=["search_knowledge"], called_tools=["search_knowledge"],
                 tool_precision=1.0, tool_recall=1.0, tool_f1=1.0, tools_exact=True,
                 retrieved_docs=["doc_interview_flow#0"], ground_truth_docs=["doc_interview_flow"],
                 recall_at_k=1.0, hit_at_k=True, answer="包含网申、笔试、面试等环节。",
                 context="国企面试流程一般分为网申、笔试、面试、体检、签约。", latency_ms=3000,
                 faithfulness=1.0, context_recall=1.0, task_completion=True),
    # 路由错 + 工具错 + 对抗失败
    SampleResult(2, "对抗性", "我投了字节算法岗，查下进度", expected_intent="qa", predicted_intent="recommend",
                 route_ok=False, golden_tools=["get_user_applications"], called_tools=[],
                 tool_precision=0.0, tool_recall=0.0, tool_f1=0.0, tools_exact=False,
                 retrieved_docs=[], ground_truth_docs=[], adversarial=1, answer="好的，我帮你看看",
                 latency_ms=5000, faithfulness=0.2, task_completion=False),
    # 超时
    SampleResult(3, "岗位推荐", "推荐北京国企算法岗", expected_intent="recommend", predicted_intent="",
                 route_ok=False, golden_tools=["search_jobs"], called_tools=[],
                 tool_precision=0.0, tool_recall=0.0, tool_f1=0.0, tools_exact=False,
                 latency_ms=180000, error="TimeoutError", timed_out=True, task_completion=None,
                 completion_unknown=True),
]
s = summarize(results)
TOL = 5e-5
check("total=3", s["total"] == 3)
check("route_accuracy=1/3", abs(s["route_accuracy"] - 1 / 3) < TOL, str(s["route_accuracy"]))
check("tool_exact_match=1/3", abs(s["tool_exact_match"] - 1 / 3) < TOL)
check("timeout_rate=1/3", abs(s["timeout_rate"] - 1 / 3) < TOL)
check("error_rate=1/3", abs(s["error_rate"] - 1 / 3) < TOL)
check("recall@K 只统计有标注的 1 条", s["retrieval_evaluated"] == 1)
check("对抗样本计数", s["adversarial_total"] == 1)
check("完成度 unknown 被单独统计", s["samples_with_unknown_completion"] == 1)
check("task_completion 只统计可判定的 2 条",
      s["evaluated"]["task_completion"] == 2, str(s["evaluated"]))
groups = by_group(results, lambda r: r.category)
check("按类别分组", set(groups) == {"面试问答", "对抗性", "岗位推荐"}, str(sorted(groups)))

print()
print("=" * 66)
print("4) 报告生成")
print("=" * 66)
md = build_markdown(s, results, category_groups=groups,
                    intent_groups=by_group(results, lambda r: r.expected_intent),
                    judge_stats={"calls": 12, "cache_hits": 3, "parse_failures": 0}, tag="selftest")
for kw in ["Route Accuracy", "Tool Accuracy", "Task Completion Rate", "Faithfulness",
           "Context Recall", "对抗性", "裁判可靠性", "口径与前提说明"]:
    check(f"报告含「{kw}」", kw in md)

print()
print("=" * 66)
print("5) Bad Case 挖掘与回归集")
print("=" * 66)
cases_by_id = {
    1: {"id": 1, "question": "国企面试流程", "category": "面试问答", "expected_intent": "qa"},
    2: {"id": 2, "question": "我投了字节算法岗，查下进度", "category": "对抗性",
        "expected_intent": "qa", "success_criteria": "必须纠正用户错误前提"},
    3: {"id": 3, "question": "推荐北京国企算法岗", "category": "岗位推荐",
        "expected_intent": "recommend"},
}
cases = mine(results, cases_by_id)
causes = summarize_causes(cases)
check("挖到 bad case", len(cases) > 0, f"{len(cases)} 条")
check("#1 不进 bad case", not any(c["id"] == 1 for c in cases))
check("#2 命中路由错误", any(c["cause"] == "route_misclassification" and c["id"] == 2 for c in cases))
check("#2 命中对抗失败", any(c["cause"] == "adversarial_failure" and c["id"] == 2 for c in cases))
check("#3 命中超时", any(c["cause"] == "case_timeout" and c["id"] == 3 for c in cases))
check("严重度排序（blocker 在前）", cases[0]["severity"] == "blocker", cases[0]["severity"])

with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "regression.jsonl"
    _, added1, total1 = update_regression_set(cases, path=p)
    check("回归集首次写入", added1 == len(cases), f"新增 {added1}")
    _, added2, total2 = update_regression_set(cases, path=p)
    check("回归集去重生效", added2 == 0 and total2 == total1, f"新增 {added2}")

print()
print("=" * 66)
if FAIL:
    print(f"自测未通过，失败项：{FAIL}")
    sys.exit(1)
print("离线管线自测全部通过")
