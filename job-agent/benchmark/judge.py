"""LLM-as-Judge（重写版）。

## 原实现的问题（都已修复）

| 问题 | 后果 |
|------|------|
| 裁判与被测**同一个模型实例**（都走 `app.llm.factory.get_chat_model()`） | 自己批改自己作业，"正确率"没有说服力 |
| JSON 解析失败 → 返回 `correctness: 0.0` | 把"判不了"当成"答错了"，系统性拉低分数且不可见 |
| 只取了 `correctness`，判官返回的 `faithfulness` / `context_utilization` **被丢弃** | 两个指标形同虚设 |
| 把 `retrieved_docs`（doc_id 列表）当"上下文文本"传给判官 | 判官看到的是一串 ID 字符串，忠实度判定完全无效 |
| 0-1 连续打分无 schema 约束 | 分数漂移，无法复现 |

## 本实现

* **独立裁判模型**（默认百炼 glm-5.3，与被测 deepseek-v4.1-flash 分离）；
* **JSON Schema 约束** + 稳健解析，解析失败记 `unknown`（一等公民，单独统计）；
* **离散判定**：蕴含 `supported/not_supported/unknown`，完成度 `pass/fail/unknown`；
* **自一致性**：可多次采样取多数票；
* **磁盘缓存**：key = hash(任务, 模型, 输入)，重复评测零成本。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

from benchmark.config import get_eval_settings

log = logging.getLogger("benchmark.judge")


# ══════════════════════════════════════════════════════════════════
# JSON 解析
# ══════════════════════════════════════════════════════════════════
def extract_json(raw: str) -> dict | None:
    """稳健抽取 JSON 对象；失败返回 None（调用方记 unknown，不猜分数）。"""
    if not raw:
        return None
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            obj = json.loads(text[start : end + 1])
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def split_claims(text: str, max_claims: int = 12) -> list[str]:
    """把一段回答切成原子陈述。

    规则切分而非让模型拆分：稳定、可复现，且把模型调用留给"判定"本身。
    """
    if not text:
        return []
    parts = re.split(r"(?<=[。！？!?；;])\s*|\n+", text)
    out = []
    for p in parts:
        p = p.strip(" \t-•*·#")
        if len(p) < 6:
            continue
        out.append(p)
        if len(out) >= max_claims:
            break
    return out


# ══════════════════════════════════════════════════════════════════
# 缓存
# ══════════════════════════════════════════════════════════════════
class JudgeCache:
    """磁盘缓存：评测动辄上千次调用，缓存让重跑接近零成本。"""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or get_eval_settings().judge_cache_file)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, Any] = {}
        self._dirty = False
        self._pending = 0
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                log.warning("裁判缓存损坏，已忽略：%s", self.path)
                self._data = {}

    @staticmethod
    def key(*parts: Any) -> str:
        payload = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

    def get(self, k: str):
        return self._data.get(k)

    def put(self, k: str, v: Any) -> None:
        self._data[k] = v
        self._dirty = True
        # **增量落盘**：每 N 条写一次磁盘。
        # 原先只在评测结束时 flush 一次，导致进程一旦卡住/被杀，
        # **整轮已完成的判定全部丢失**（实测卡死 2.5 小时、上千次调用白跑）。
        # 增量落盘后，最坏只损失最近 N 条。
        self._pending = getattr(self, "_pending", 0) + 1
        if self._pending >= 20:
            self.flush()
            self._pending = 0

    def flush(self) -> None:
        if not self._dirty:
            return
        try:
            # 先写临时文件再原子替换：避免写一半被中断导致缓存损坏，
            # 进而让下一次运行从头再算一遍。
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
            self._dirty = False
        except Exception as exc:  # noqa: BLE001
            log.warning("裁判缓存写入失败：%s", exc)

    def __len__(self) -> int:
        return len(self._data)


# ══════════════════════════════════════════════════════════════════
# 裁判
# ══════════════════════════════════════════════════════════════════
_ENTAIL_SYSTEM = (
    "你是严格的文本蕴含判定器。只判断【证据】是否支持【陈述】，"
    "不要使用你自己的知识，不要脑补。"
    "证据中明确写出或可直接推出 → supported；"
    "证据没有提到、或与证据冲突 → not_supported；"
    "证据为空 → unknown。"
    '必须只输出 JSON：{"verdict":"supported"}'
)

_COMPLETE_SYSTEM = (
    "你是评测员。严格按【验收标准】判断【回答】是否达标，"
    "不要因为回答语气好、篇幅长就给通过。"
    "达标 → pass；未达标或答非所问 → fail；无法判断 → unknown。"
    '必须只输出 JSON：{"verdict":"pass"}'
)

_RELEVANCE_SYSTEM = (
    "你判断一段检索结果是否与用户问题相关（是否有助于回答该问题）。"
    "相关 → relevant；无关 → irrelevant；无法判断 → unknown。"
    '必须只输出 JSON：{"verdict":"relevant"}'
)


class Judge:
    def __init__(self, model: str | None = None, cache: JudgeCache | None = None,
                 samples: int | None = None) -> None:
        s = get_eval_settings()
        self.model_name = model or s.judge_model
        self.samples = max(1, int(samples if samples is not None else s.judge_samples))
        self.cache = cache or JudgeCache()
        self._model = None
        # in_tokens / out_tokens 用于**额度核算**：裁判是推理模型，一次判定可能
        # 消耗上千 token，跑全量前必须知道总用量是否在额度内。
        self.stats = {
            "calls": 0, "cache_hits": 0, "parse_failures": 0, "unknowns": 0,
            "in_tokens": 0, "out_tokens": 0, "reasoning_loops": 0,
        }

    # -- 惰性构造：避免评测未开始时就去连网 --
    @property
    def model(self):
        if self._model is None:
            from langchain_openai import ChatOpenAI

            s = get_eval_settings()
            if not s.judge_api_key:
                raise RuntimeError("缺少裁判 API Key：请在 .env 设置 OPENAI_API_KEY")
            self._model = ChatOpenAI(
                model=self.model_name,
                api_key=s.judge_api_key,
                base_url=s.judge_endpoint,
                temperature=s.judge_temperature,
                max_tokens=s.judge_max_tokens,
                timeout=s.judge_timeout,
                max_retries=2,
                model_kwargs={"response_format": {"type": "json_object"}},
            )
        return self._model

    async def _ask(self, system: str, prompt: str, max_tokens: int | None = None) -> dict | None:
        from langchain_core.messages import HumanMessage, SystemMessage

        model = self.model
        if max_tokens is not None:
            model = model.bind(max_tokens=max_tokens)

        # **硬性墙钟超时**（asyncio 层，不是 httpx 层）。
        # 踩过的坑：`ChatOpenAI(timeout=120)` 配了超时，但在"半开连接"
        # （对端已建立 TCP、却一直不返回数据）上并不会触发 ——
        # 实测进程挂死 **2.5 小时**、CPU 累计仅 5 秒、缓存零增长。
        # asyncio.wait_for 在事件循环层面强制中断，不受底层 socket 行为影响。
        s = get_eval_settings()
        try:
            resp = await asyncio.wait_for(
                model.ainvoke([SystemMessage(content=system), HumanMessage(content=prompt)]),
                timeout=s.judge_timeout + 5,
            )
        except asyncio.TimeoutError as exc:
            raise TimeoutError(
                f"裁判调用超过 {s.judge_timeout + 5}s 未返回（疑似连接挂起）"
            ) from exc
        # 累计 token 用量，供额度核算
        um = getattr(resp, "usage_metadata", None) or {}
        self.stats["in_tokens"] += int(um.get("input_tokens", 0) or 0)
        self.stats["out_tokens"] += int(um.get("output_tokens", 0) or 0)
        return extract_json(resp.content if isinstance(resp.content, str) else str(resp.content))

    async def _vote(self, system: str, prompt: str, field: str, allowed: tuple[str, ...]):
        """多次采样取多数；返回 (值, 一致率)。全部失败返回 (None, 0.0)。"""
        s = get_eval_settings()
        ck = JudgeCache.key("judge", self.model_name, self.samples, system, prompt)
        cached = self.cache.get(ck)
        if cached is not None:
            self.stats["cache_hits"] += 1
            return cached.get("value"), cached.get("agreement", 1.0)

        votes: list[str] = []
        for _ in range(self.samples):
            obj = None
            # 两轮**相同预算**重试。
            # 注意：这里刻意**不做预算加倍**。实测 glm-5.3 偶发思考死循环
            # （小提示词也能吃满 8192 且不终止，单次耗时约 128 秒），
            # 这是随机病态行为而非"额度不够"——加倍预算只会让它烧掉更多。
            # 正常调用的思考量仅 60-200 token，重采样一次基本都能成功。
            for attempt in range(2):
                self.stats["calls"] += 1
                try:
                    obj = await self._ask(system, prompt)
                except Exception as exc:  # noqa: BLE001
                    name = type(exc).__name__
                    if "Length" in name or "length limit" in str(exc):
                        self.stats["reasoning_loops"] = self.stats.get("reasoning_loops", 0) + 1
                        log.warning("裁判疑似思考死循环，重采样（第 %d 次）", attempt + 1)
                    else:
                        log.warning("裁判调用失败（第 %d 次）：%s: %s",
                                    attempt + 1, name, str(exc)[:200])
                    obj = None
                if obj and obj.get(field) in allowed:
                    break
                if attempt == 0:
                    continue
            if not obj or obj.get(field) not in allowed:
                self.stats["parse_failures"] += 1
                continue
            votes.append(obj[field])

        if not votes:
            self.stats["unknowns"] += 1
            # **不缓存失败结果**。
            # 踩过的坑：曾把 value=None 也写进缓存，导致后续重跑直接命中"失败的缓存"
            # 而立刻返回 unknown —— 即使代码/额度已经修好，也永远得不到判定，
            # 且表面上看是"缓存命中"（很快），极难察觉。
            return None, 0.0

        counts: dict[str, int] = {}
        for v in votes:
            counts[v] = counts.get(v, 0) + 1
        best = max(counts, key=lambda k: counts[k])
        agreement = counts[best] / len(votes)
        self.cache.put(ck, {"value": best, "agreement": agreement})
        return best, agreement

    # -- 批量判定（token 优化的关键）--
    async def _judge_list(self, system: str, prompt: str, n: int,
                          allowed: tuple[str, ...]) -> list[str] | None:
        """一次调用判定 n 条，返回长度 n 的列表；失败返回 None（由调用方降级）。

        为什么批量：实测忠实度占裁判 token 的 **74%**，根因是逐条判定时
        **每条陈述都要重发一遍完整上下文（约 2500 token）**，
        75 题 737 条陈述 = 上下文被重复发送 737 次。
        批量后上下文一个用例只发一次，该项消耗可从约 1.88M 降到约 0.23M。
        """
        s = get_eval_settings()
        ck = JudgeCache.key("judge_batch", self.model_name, 1, system, prompt)
        cached = self.cache.get(ck)
        if cached is not None and isinstance(cached.get("verdicts"), list):
            vals = cached["verdicts"]
            if len(vals) == n:
                self.stats["cache_hits"] += 1
                return [v if v in allowed else "unknown" for v in vals]

        for attempt in range(2):
            self.stats["calls"] += 1
            try:
                obj = await self._ask(system, prompt)
            except Exception as exc:  # noqa: BLE001
                name = type(exc).__name__
                if "Length" in name or "length limit" in str(exc):
                    self.stats["reasoning_loops"] = self.stats.get("reasoning_loops", 0) + 1
                    log.warning("批量裁判疑似思考死循环，重采样（第 %d 次）", attempt + 1)
                else:
                    log.warning("批量裁判失败（第 %d 次）：%s: %s",
                                attempt + 1, name, str(exc)[:160])
                obj = None
            if obj:
                vals = obj.get("verdicts")
                if isinstance(vals, list) and len(vals) == n:
                    out = [v if v in allowed else "unknown" for v in vals]
                    self.cache.put(ck, {"verdicts": out})
                    return out
                if isinstance(vals, list):
                    log.warning("批量裁判返回 %d 项，期望 %d 项，本次作废",
                                len(vals), n)
        return None

    async def entailment_batch(self, context: str, claims: list[str]) -> list[str]:
        """一次调用判定多条陈述的蕴含关系，返回与 claims 等长的判定列表。

        仅当 `judge_batch=True` 时由评测调用；否则调用方走逐条路径。
        """
        if not claims:
            return []
        if not context.strip():
            return ["unknown"] * len(claims)
        if not get_eval_settings().judge_batch:
            res = []
            for c in claims:
                v, _ = await self.entailment(context, c)
                res.append(v)
            return res

        limit = get_eval_settings().judge_context_chars
        lines = "\n".join(f"{i + 1}. {c[:300]}" for i, c in enumerate(claims))
        prompt = (
            f"【证据】\n{context[:limit]}\n\n"
            f"【陈述列表】共 {len(claims)} 条\n{lines}\n\n"
            "逐条判断每条陈述能否由上述证据支撑：\n"
            "  supported     —— 证据直接支持\n"
            "  not_supported —— 证据无法支持（含证据中未提及）\n"
            "  unknown       —— 证据不足以判断\n"
            f'只输出 JSON：{{"verdicts":["supported","not_supported",...]}}，'
            f"顺序与输入一致，必须恰好 {len(claims)} 项。"
        )
        out = await self._judge_list(
            _ENTAIL_SYSTEM, prompt, len(claims),
            ("supported", "not_supported", "unknown"),
        )
        if out is not None:
            return out

        # 降级：批量失败才退回逐条（更贵但更稳）
        log.warning("批量蕴含判定失败，退回逐条判定（%d 条）", len(claims))
        res = []
        for c in claims:
            v, _ = await self.entailment(context, c)
            res.append(v)
        return res

    async def relevance_batch(self, question: str, chunks: list[str]) -> list[str]:
        """一次调用判定多个检索片段的相关性，返回与 chunks 等长的列表。"""
        if not chunks:
            return []
        if not get_eval_settings().judge_batch:
            res = []
            for c in chunks:
                v, _ = await self.relevance(question, c)
                res.append(v)
            return res

        listing = "\n\n".join(
            f"[片段 {i + 1}]\n{c[:600]}" for i, c in enumerate(chunks)
        )
        prompt = (
            f"【用户问题】\n{question}\n\n"
            f"【检索到的片段】共 {len(chunks)} 个\n{listing}\n\n"
            "逐个判断每个片段是否有助于回答该问题。"
            f'只输出 JSON：{{"verdicts":["relevant","irrelevant",...]}}，'
            f"顺序与输入一致，必须恰好 {len(chunks)} 项。"
        )
        out = await self._judge_list(
            _RELEVANCE_SYSTEM, prompt, len(chunks),
            ("relevant", "irrelevant", "unknown"),
        )
        if out is not None:
            return out

        log.warning("批量相关性判定失败，退回逐条判定（%d 个）", len(chunks))
        res = []
        for c in chunks:
            v, _ = await self.relevance(question, c)
            res.append(v)
        return res

    # -- 三项判定 --
    async def entailment(self, context: str, claim: str) -> tuple[str, float]:
        if not context.strip():
            return "unknown", 1.0
        # 上下文截断长度可配：实测这是裁判 token 的**主要成本来源**
        # （每次调用都要重发一遍上下文），调小可直接线性降本。
        limit = get_eval_settings().judge_context_chars
        prompt = (
            f"【证据】\n{context[:limit]}\n\n【陈述】\n{claim[:500]}\n\n"
            '上面的证据是否支持该陈述？只输出 JSON，如 {"verdict":"supported"}'
        )
        v, a = await self._vote(_ENTAIL_SYSTEM, prompt, "verdict",
                                ("supported", "not_supported", "unknown"))
        return (v or "unknown"), a

    async def task_completion(self, question: str, answer: str, criteria: str,
                              context: str = "") -> tuple[str, float]:
        prompt = (
            f"【用户问题】\n{question}\n\n"
            f"【待评回答】\n{answer[:1500]}\n\n"
            f"【参考资料】\n{context[:1500] if context else '（无）'}\n\n"
            f"【验收标准】\n{criteria}\n\n"
            '只输出 JSON，如 {"verdict":"pass"}'
        )
        v, a = await self._vote(_COMPLETE_SYSTEM, prompt, "verdict",
                                ("pass", "fail", "unknown"))
        return (v or "unknown"), a

    async def relevance(self, question: str, chunk: str) -> tuple[str, float]:
        prompt = (
            f"【用户问题】\n{question}\n\n【检索到的片段】\n{chunk[:1200]}\n\n"
            '只输出 JSON，如 {"verdict":"relevant"}'
        )
        v, a = await self._vote(_RELEVANCE_SYSTEM, prompt, "verdict",
                                ("relevant", "irrelevant", "unknown"))
        return (v or "unknown"), a

    def flush(self) -> None:
        self.cache.flush()


async def self_test() -> int:
    """裁判连通性自检：评测前先跑，避免跑到一半才发现 key/模型不对。"""
    s = get_eval_settings()
    print(f"裁判模型   : {s.judge_model}")
    print(f"裁判端点   : {s.judge_endpoint}")
    print(f"API Key    : {'已配置' if s.judge_api_key else '缺失 ✗'}")
    if not s.judge_api_key:
        return 1

    j = Judge(samples=1)
    print("· 蕴含判定 ...", end=" ", flush=True)
    v1, _ = await j.entailment(
        "国企面试流程一般分为网申、笔试、面试、体检、签约几个环节。",
        "国企面试包含网申和笔试环节。",
    )
    print(v1)

    print("· 任务完成度 ...", end=" ", flush=True)
    v2, _ = await j.task_completion(
        "国企面试流程是什么",
        "一般包括网申、笔试、面试（一面/二面/终面）、体检、签约五个环节。",
        "必须说明面试的主要环节，至少覆盖网申与笔试。",
    )
    print(v2)

    j.flush()
    ok = v1 in ("supported", "not_supported") and v2 in ("pass", "fail")
    print(f"调用统计   : {j.stats}")
    print("自检结果   :", "通过" if ok else "异常（裁判未给出有效判定）")
    return 0 if ok else 1
