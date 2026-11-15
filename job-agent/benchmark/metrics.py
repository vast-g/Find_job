"""评测指标（重写版）。

对应简历里要量化的五项核心能力，外加检索质量与运行健康度。

## 指标口径

| 指标 | 口径 | 数据来源 |
|---|---|---|
| Route Accuracy（意图路由） | 预测意图 == 期望意图 | `pipeline.handle()` 返回的 `intent` |
| Tool Accuracy | 期望工具集 vs 实调工具集的 P/R/F1 + 完全匹配率 | `stats.tool_calls` |
| Task Completion Rate | 按 `success_criteria` 判定 pass/fail | 裁判 |
| Faithfulness | 回答拆原子陈述，逐条判断能否被**检索到的上下文内容**蕴含 | 裁判 |
| Context Recall | 标准答案要点能否在检索上下文中找到支撑 | 裁判 |
| Recall@K / MRR | 检索命中的 doc_id 与 `ground_truth_docs` 比对 | 检索结果 |
| 运行健康度 | 延迟分位、token、成本、错误率、超时率 | `stats` |

## 三个关键取舍

1. **路由与工具走确定性断言**，不用裁判 —— 有精确解，用 LLM 打分只会引入噪声。
2. **判定三值**（supported/not_supported/unknown），`unknown` 单独统计，不折算成分数。
3. **判官拿的是上下文正文**（`retrieved_docs[].content`），不是 doc_id ——
   原实现传的是 ID 列表，却当文本用，忠实度判定实际无效。

## doc_id 匹配规则

索引时 doc_id 形如 `doc_interview_flow#0`（`#` 后是分块序号），
数据集的 `ground_truth_docs` 只写到源文档（`doc_interview_flow`）。
因此比对时**按前缀匹配**，避免把"同一文档的其它分块"误判为未召回。
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any, Optional

from benchmark.config import get_eval_settings
from benchmark.judge import Judge, split_claims

DOC_SEP = "#"


def doc_base(doc_id: str) -> str:
    """去掉分块序号，取源文档 ID。"""
    return (doc_id or "").split(DOC_SEP)[0]


def match_docs(retrieved: list[str], ground_truth: list[str]) -> set[str]:
    """返回被命中的 ground_truth 文档集合（按源文档前缀匹配）。"""
    got = {doc_base(d) for d in retrieved if d}
    return {g for g in ground_truth if doc_base(g) in got}


def tool_scores(expected: list[str], predicted: list[str]) -> tuple[float, float, float, bool]:
    """工具调用集合评分。空期望+空预测=正确；空期望+有预测=误调用。"""
    e, p = set(expected or []), set(predicted or [])
    exact = e == p
    if not e and not p:
        return 1.0, 1.0, 1.0, True
    tp = len(e & p)
    precision = tp / len(p) if p else 0.0
    recall = tp / len(e) if e else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return round(precision, 4), round(recall, 4), round(f1, 4), exact


@dataclass
class SampleResult:
    """单条用例的评测结果。"""

    id: int
    category: str
    question: str
    difficulty: int = 1
    adversarial: int = 0

    # 路由（意图）
    expected_intent: str = ""
    predicted_intent: str = ""
    route_ok: Optional[bool] = None

    # 工具
    golden_tools: list[str] = field(default_factory=list)
    called_tools: list[str] = field(default_factory=list)
    tool_precision: Optional[float] = None
    tool_recall: Optional[float] = None
    tool_f1: Optional[float] = None
    tools_exact: Optional[bool] = None

    # 检索
    retrieved_docs: list[str] = field(default_factory=list)
    ground_truth_docs: list[str] = field(default_factory=list)
    recall_at_k: Optional[float] = None
    hit_at_k: Optional[bool] = None

    # 运行
    answer: str = ""
    context: str = ""
    latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    error: str = ""
    timed_out: bool = False

    # 裁判
    faithfulness: Optional[float] = None
    context_recall: Optional[float] = None
    context_relevance: Optional[float] = None
    task_completion: Optional[bool] = None
    completion_unknown: bool = False

    judge_unknowns: int = 0
    judge_agreements: list[float] = field(default_factory=list)


class Evaluator:
    def __init__(self, judge: Judge, *, use_judge: bool = True, k: int = 5) -> None:
        self.judge = judge
        self.use_judge = use_judge
        self.k = k

    # ---------- 单条 ----------
    async def evaluate_sample(self, case: dict, run: dict | None) -> SampleResult:
        r = SampleResult(
            id=case.get("id", -1),
            category=case.get("category", ""),
            question=case.get("question", ""),
            difficulty=case.get("difficulty", 1),
            adversarial=case.get("adversarial", 0),
            expected_intent=case.get("expected_intent", ""),
            golden_tools=list(case.get("golden_tools") or []),
            ground_truth_docs=list(case.get("ground_truth_docs") or []),
        )

        if run is None:
            r.error = "未采集到运行结果"
            r.route_ok = False
            r.tool_precision = r.tool_recall = r.tool_f1 = 0.0
            r.tools_exact = False
            r.task_completion = False
            if r.ground_truth_docs:
                r.recall_at_k = 0.0
                r.hit_at_k = False
            return r

        # ---- 确定性指标 ----
        r.predicted_intent = run.get("intent") or ""
        r.route_ok = r.predicted_intent == r.expected_intent

        r.called_tools = list(run.get("tool_calls") or [])
        r.tool_precision, r.tool_recall, r.tool_f1, r.tools_exact = tool_scores(
            r.golden_tools, r.called_tools
        )

        r.retrieved_docs = [d.get("doc_id", "") for d in (run.get("retrieved_docs") or [])]
        if r.ground_truth_docs:
            hit = match_docs(r.retrieved_docs, r.ground_truth_docs)
            r.recall_at_k = round(len(hit) / len(r.ground_truth_docs), 4)
            r.hit_at_k = bool(hit)

        # ---- 运行信息 ----
        r.answer = run.get("answer") or ""
        r.latency_ms = float(run.get("latency_ms") or 0.0)
        r.prompt_tokens = int(run.get("prompt_tokens") or 0)
        r.completion_tokens = int(run.get("completion_tokens") or 0)
        r.cost_usd = float(run.get("cost_usd") or 0.0)
        r.error = run.get("error") or ""
        r.timed_out = bool(run.get("timed_out"))

        # 供裁判使用的上下文：用**正文**而非 doc_id。
        #
        # 两个来源合并，缺一不可：
        #   1. retrieved_docs —— search_knowledge 的结构化检索结果（含 doc_id）
        #   2. tool_outputs   —— **所有**工具的返回正文（简历、岗位搜索结果等）
        # 只取第 1 项会导致岗位推荐/简历优化类用例"没有上下文"，
        # 忠实度被直接判 0（假阴性）。实测 75 题里有 39 题属于这种情况。
        parts: list[str] = []
        for d in (run.get("retrieved_docs") or []):
            c = (d.get("content") or "").strip()
            if c:
                parts.append(c)
        # 工具原文可能已包含检索结果，去重避免同一段材料重复计入
        seen = set(parts)
        for t in (run.get("tool_outputs") or []):
            t = (t or "").strip()
            if t and t not in seen:
                seen.add(t)
                parts.append(t)
        r.context = "\n\n".join(parts)

        # ---- 裁判指标 ----
        if self.use_judge:
            await self._judge(case, r)
        return r

    async def _judge(self, case: dict, r: SampleResult) -> None:
        # Faithfulness：回答的原子陈述能否被上下文支持。
        # 用**批量**判定：逐条判定会把完整上下文重复发送 N 次，
        # 实测忠实度因此占掉裁判 74% 的 token。批量后一个用例只发一次上下文。
        claims = split_claims(r.answer)
        # 限制每题判定的陈述数：token 成本与陈述数成正比，
        # 而忠实度本质是**比率**，抽样若干条即可代表，无需逐句穷举。
        cap = get_eval_settings().judge_max_claims
        if cap and len(claims) > cap:
            claims = claims[:cap]
        if claims:
            if not r.context.strip():
                # 没有上下文却给事实性回答 → 无从支撑（保持原口径）
                r.faithfulness = 0.0
            else:
                verdicts = await self.judge.entailment_batch(r.context, claims)
                ok = sum(1 for v in verdicts if v == "supported")
                r.judge_unknowns += sum(1 for v in verdicts if v == "unknown")
                r.faithfulness = round(ok / len(claims), 4)

        # Context Recall：标准答案要点能否在上下文中找到支撑（同样批量）
        points = (case.get("expected") or {}).get("关键点") or []
        if points and r.ground_truth_docs:
            if not r.context.strip():
                r.context_recall = 0.0
            else:
                ptexts = [str(p) for p in points]
                verdicts = await self.judge.entailment_batch(r.context, ptexts)
                hit = sum(1 for v in verdicts if v == "supported")
                r.judge_unknowns += sum(1 for v in verdicts if v == "unknown")
                r.context_recall = round(hit / len(ptexts), 4)

        # Context Relevance：召回片段是否切题（批量）
        chunks = [c for c in r.context.split("\n\n") if len(c.strip()) >= 20][:12]
        if chunks:
            verdicts = await self.judge.relevance_batch(r.question, chunks)
            rel = sum(1 for v in verdicts if v == "relevant")
            r.judge_unknowns += sum(1 for v in verdicts if v == "unknown")
            r.context_relevance = round(rel / len(chunks), 4)

        # Task Completion
        criteria = case.get("success_criteria") or self._default_criteria(case)
        v, a = await self.judge.task_completion(r.question, r.answer, criteria, r.context)
        r.judge_agreements.append(a)
        if v == "pass":
            r.task_completion = True
        elif v == "fail":
            r.task_completion = False
        else:
            r.task_completion = None
            r.completion_unknown = True
            r.judge_unknowns += 1

    @staticmethod
    def _default_criteria(case: dict) -> str:
        cat = case.get("category", "")
        if cat == "岗位推荐":
            return "必须给出具体岗位方向或检索结果，并说明推荐理由；不得编造不存在的岗位数据。"
        if cat == "简历优化":
            return "必须给出可执行的修改建议，最好结合目标岗位要求；不得空泛说教。"
        if cat == "面试问答":
            return "必须基于知识库给出准确回答，覆盖问题核心；不得编造流程或标准。"
        if cat == "对抗性" or case.get("adversarial"):
            return "必须识别并纠正用户的错误前提或超范围诉求，不得逢迎附和；应明确说明事实。"
        return "回答必须直接回应用户问题，事实性内容准确，不得编造。"


# ══════════════════════════════════════════════════════════════════
# 汇总
# ══════════════════════════════════════════════════════════════════
def _mean(vals: list[Optional[float]]) -> Optional[float]:
    xs = [v for v in vals if v is not None]
    return round(statistics.fmean(xs), 4) if xs else None


def _rate(flags: list[Optional[bool]]) -> Optional[float]:
    xs = [f for f in flags if f is not None]
    return round(sum(1 for x in xs if x) / len(xs), 4) if xs else None


def _pct(vals: list[float], p: float) -> Optional[float]:
    if not vals:
        return None
    s = sorted(vals)
    k = (len(s) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return round(s[f] + (s[c] - s[f]) * (k - f), 1)


def summarize(results: list[SampleResult]) -> dict[str, Any]:
    n = len(results)
    if n == 0:
        return {"total": 0}

    lat = [r.latency_ms for r in results if r.latency_ms > 0]
    agreements = [a for r in results for a in r.judge_agreements]
    adv = [r for r in results if r.adversarial]

    return {
        "total": n,
        # ── 五项核心 ──
        "route_accuracy": _rate([r.route_ok for r in results]),
        "tool_f1": _mean([r.tool_f1 for r in results]),
        "tool_exact_match": _rate([r.tools_exact for r in results]),
        "tool_precision": _mean([r.tool_precision for r in results]),
        "tool_recall": _mean([r.tool_recall for r in results]),
        "task_completion_rate": _rate([r.task_completion for r in results]),
        "faithfulness": _mean([r.faithfulness for r in results]),
        "context_recall": _mean([r.context_recall for r in results]),
        "context_relevance": _mean([r.context_relevance for r in results]),
        # ── 检索 ──
        "recall_at_k": _mean([r.recall_at_k for r in results if r.ground_truth_docs]),
        "hit_at_k": _rate([r.hit_at_k for r in results if r.ground_truth_docs]),
        "retrieval_evaluated": sum(1 for r in results if r.ground_truth_docs),
        # ── 对抗性专项 ──
        "adversarial_total": len(adv),
        "adversarial_completion_rate": _rate([r.task_completion for r in adv]) if adv else None,
        # ── 运行健康度 ──
        "error_rate": _rate([bool(r.error) for r in results]),
        "timeout_rate": _rate([r.timed_out for r in results]),
        "latency_p50_ms": _pct(lat, 50),
        "latency_p90_ms": _pct(lat, 90),
        "latency_mean_ms": round(statistics.fmean(lat), 1) if lat else None,
        "total_prompt_tokens": sum(r.prompt_tokens for r in results),
        "total_completion_tokens": sum(r.completion_tokens for r in results),
        "total_cost_usd": round(sum(r.cost_usd for r in results), 6),
        # ── 裁判可靠性 ──
        "judge_agreement_mean": _mean(agreements),
        "judge_unknown_total": sum(r.judge_unknowns for r in results),
        "samples_with_unknown_completion": sum(1 for r in results if r.completion_unknown),
        "evaluated": {
            "faithfulness": sum(1 for r in results if r.faithfulness is not None),
            "context_recall": sum(1 for r in results if r.context_recall is not None),
            "task_completion": sum(1 for r in results if r.task_completion is not None),
        },
    }


def by_group(results: list[SampleResult], key) -> dict[str, dict]:
    groups: dict[str, list[SampleResult]] = {}
    for r in results:
        groups.setdefault(str(key(r)), []).append(r)
    return {k: summarize(v) for k, v in sorted(groups.items())}


__all__ = [
    "SampleResult", "Evaluator", "summarize", "by_group",
    "tool_scores", "match_docs", "doc_base",
]
