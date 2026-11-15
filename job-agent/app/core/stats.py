"""运行统计：在整条链路中累积 token、检索文档、工具调用，供评测与计费。"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.config import get_settings

log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════
#  计价
#
#  ⚠️ **必须按模型计价，不能按 provider 计价** —— 这是踩过的坑：
#
#  LLM_PROVIDER=openai 只表示"使用 OpenAI 兼容协议"（百炼、DeepSeek、
#  vLLM 等等都用这个协议），**完全不代表用的是 OpenAI 的模型**。
#  原来的写法是按 provider 查表，于是百炼上的 deepseek-flash 被套上了
#  GPT-4 级别的价格（$0.005 / $0.015 每 1K token），实际便宜一两个数量级。
#
#  后果不是"报表数字偏大"这么轻 —— react_agent 里有一句事后预算兜底：
#      if checker.over_budget(stats.cost_usd): return FALLBACK_REPLY
#  成本被算高 → **每个请求都判成超预算** → ReAct 明明已经完整跑完
#  （20 多秒、token 也真花了），答案却被丢掉，用户看到的是
#  "抱歉，这个问题处理超时了"。**钱花了、答案没了**，而且报错信息
#  完全指不到计费上，极难排查。
#
#  所以这里的策略是：**按模型名（含前缀）匹配；匹配不到就按 0 计并告警**。
#  宁可"预算管不住"也不能"功能被算坏" —— 真正的成本护栏是
#  MAX_REACT_STEPS 与 TIMEOUT_SECONDS，它们不依赖价格表。
# ══════════════════════════════════════════════════════════════════

# 每 1K token 价格（输入, 输出），美元。按**模型名前缀**匹配，长前缀优先。
#
# ⚠️ 这些数字是按 DeepSeek 官方公开价格折算的量级参考（¥2 / ¥8 每百万 token），
#    **百炼的实际计费请以控制台账单为准**。差异不影响系统正确性
#    （价格只用于预算报表与护栏），但会影响成本统计的准确性。
#    可以用 .env 覆盖：LLM_PRICE_IN_PER_1K / LLM_PRICE_OUT_PER_1K
MODEL_PRICE_PER_1K: dict[str, tuple[float, float]] = {
    "deepseek": (0.00028, 0.00110),
    "qwen": (0.0, 0.0),          # 本地 Ollama 跑，不花钱
    "gpt-": (0.005, 0.015),      # 真用 OpenAI 时才适用
    "claude": (0.003, 0.015),
    "gemini": (0.00125, 0.005),
}

# 兜底：只有模型名完全匹配不上时才用 provider
PROVIDER_PRICE_PER_1K: dict[str, tuple[float, float]] = {
    "qwen": (0.0, 0.0),
    "ollama": (0.0, 0.0),
}

_warned_models: set[str] = set()


def _lookup_price(model: str, provider: str) -> tuple[float, float]:
    """先按模型名（长前缀优先）匹配，再退回 provider，最后按 0 计并告警。"""
    s = get_settings()

    # 1) .env 显式覆盖优先（价格变动时无需改代码）
    in_ov = getattr(s, "llm_price_in_per_1k", None)
    out_ov = getattr(s, "llm_price_out_per_1k", None)
    if in_ov is not None and out_ov is not None:
        return float(in_ov), float(out_ov)

    # 2) 按模型名前缀匹配（按长度降序，保证 "deepseek-v4-pro" 优先于 "deepseek"）
    m = (model or "").lower()
    for prefix in sorted(MODEL_PRICE_PER_1K, key=len, reverse=True):
        if m.startswith(prefix.lower()):
            return MODEL_PRICE_PER_1K[prefix]

    # 3) 退回 provider
    p = (provider or "").lower()
    if p in PROVIDER_PRICE_PER_1K:
        return PROVIDER_PRICE_PER_1K[p]

    # 4) 都不认识 → 按 0 计，但**必须告警**。
    #    静默按 0 计会让人以为"不要钱"；静默按高值计会像上面那样把功能算坏。
    if model not in _warned_models:
        _warned_models.add(model)
        log.warning(
            "模型 %r（provider=%s）不在价格表里，成本按 0 计 —— "
            "预算护栏对该模型不生效。如需统计成本，请在 .env 里设置 "
            "LLM_PRICE_IN_PER_1K / LLM_PRICE_OUT_PER_1K。", model, provider)
    return 0.0, 0.0



@dataclass
class RunStats:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    retrieved_docs: list[dict] = field(default_factory=list)
    tool_calls: list[str] = field(default_factory=list)
    # 所有工具的原始输出（不只 search_knowledge）。
    # 用途：忠实度判定需要"回答所依据的材料"，而岗位推荐/简历优化类回答
    # 依据的是 get_user_resume / search_jobs 的返回，不是知识库检索结果。
    # 只记录 retrieved_docs 会让这些用例"没有上下文"，忠实度被误判为 0。
    tool_outputs: list[str] = field(default_factory=list)

    def add_usage(self, usage: dict | None) -> None:
        if not usage:
            return
        self.prompt_tokens += int(usage.get("prompt_tokens", 0))
        self.completion_tokens += int(usage.get("completion_tokens", 0))

    def add_tool_call(self, name: str) -> None:
        self.tool_calls.append(name)

    def add_retrieved_docs(self, docs: list[dict]) -> None:
        self.retrieved_docs.extend(docs)

    def add_tool_output(self, text: str) -> None:
        """记录一次工具返回的正文（用于忠实度判定的"依据材料"）。"""
        if text and text.strip():
            self.tool_outputs.append(text)

    @property
    def cost_usd(self) -> float:
        s = get_settings()
        in_price, out_price = _lookup_price(
            getattr(s, "llm_model", ""), getattr(s, "llm_provider", ""))
        return (self.prompt_tokens / 1000 * in_price) + (self.completion_tokens / 1000 * out_price)

    def as_dict(self) -> dict:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "retrieved_docs": self.retrieved_docs,
            "tool_calls": self.tool_calls,
            "tool_outputs": self.tool_outputs,
        }
