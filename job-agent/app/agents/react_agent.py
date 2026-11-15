"""ReAct Agent：基于 LangChain create_agent（内部是 LangGraph 状态图）。

## 终止条件

- `recursion_limit`（LangGraph 原生步数上限）
- `asyncio.wait_for` 超时
- 预算由 stats.cost_usd 事后校验（超出返回兜底话术）

## 两个实测踩过的坑

1. **`recursion_limit` 不是"ReAct 轮数"**
   LangGraph 统计的是**图节点执行次数**：每一轮 ReAct 包含 `agent` 节点（调模型）
   和 `tools` 节点（执行工具）两次执行。把"最大轮数"直接当 `recursion_limit`
   传进去，实际可用的轮数只有一半 —— 表现为 Agent 明明还该继续检索却提前收尾。

2. **步数耗尽时 LangGraph 不抛异常，而是返回一句内部提示**
   文档原文：*If `remaining_steps` is less than 2 and tool calls are present,
   the react agent will return a final AI Message with the content
   "Sorry, need more steps to process this request."*
   这句话曾被原样返回给终端用户（实测在评测的失败样本里抓到）。
   现在统一识别并替换为面向用户的话术。

可观测：传入 ObservabilityCallbackHandler 采集 token/工具/检索并写 agent_trace。
"""
from __future__ import annotations

import asyncio
import logging

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
# ⚠️ create_react_agent 在 LangGraph V1.0 已废弃（V2.0 移除），
# 官方迁移路径是 langchain.agents.create_agent —— 返回的同样是
# CompiledStateGraph，节点与边结构一致，只有「调模型那个节点」
# 从 `agent` 改名成了 `model`（本仓库没有代码按节点名取值）。
from langchain.agents import create_agent

from app.core.stats import RunStats
from app.core.termination import FALLBACK_REPLY, STEP_LIMIT_REPLY, TerminationChecker
from app.llm.factory import get_chat_model
from app.observability.callback import ObservabilityCallbackHandler
from app.tools.registry import get_tools, get_tools_by_name

log = logging.getLogger("app.agents.react")

# LangGraph 步数耗尽时返回的内部提示（非异常，是正常返回值）
_NEED_MORE_STEPS = "Sorry, need more steps to process this request."


def recursion_limit_for(max_turns: int) -> int:
    """把"最大 ReAct 轮数"换算成 LangGraph 的 recursion_limit。

    每轮 = agent 节点 + tools 节点 = 2 次执行，再加 1 步余量让最后一轮能正常收尾。
    """
    return max(2, max_turns * 2 + 1)


class ReActAgent:
    def __init__(self, model: BaseChatModel | None = None):
        self.model = model or get_chat_model()

    async def run(
        self,
        messages: list[BaseMessage],
        tool_names: list[str] | None = None,
        checker: TerminationChecker | None = None,
        stats: RunStats | None = None,
        callback: ObservabilityCallbackHandler | None = None,
    ) -> str:
        checker = checker or TerminationChecker()
        tools = get_tools_by_name(tool_names) if tool_names else get_tools()
        agent = create_agent(self.model, tools)

        limit = recursion_limit_for(checker.max_steps)
        config: dict = {"recursion_limit": limit}
        if callback is not None:
            config["callbacks"] = [callback]

        try:
            result = await asyncio.wait_for(
                agent.ainvoke({"messages": messages}, config=config),
                timeout=checker.timeout_seconds,
            )
        except asyncio.TimeoutError:
            log.warning("ReAct 超时（%ss，recursion_limit=%d）", checker.timeout_seconds, limit)
            return FALLBACK_REPLY
        except Exception as exc:  # noqa: BLE001
            # GraphRecursionError 等：不能让库的异常信息冒到用户面前
            name = type(exc).__name__
            if "Recursion" in name:
                log.warning("ReAct 步数耗尽（recursion_limit=%d，最大轮数=%d）",
                            limit, checker.max_steps)
                return STEP_LIMIT_REPLY
            log.exception("ReAct 执行异常：%s", name)
            return FALLBACK_REPLY

        # 超预算兜底
        if stats is not None and checker.over_budget(stats.cost_usd):
            log.warning("超出预算：$%.4f > $%.4f", stats.cost_usd, checker.max_budget_usd)
            return FALLBACK_REPLY

        final = result["messages"][-1]
        content = final.content if getattr(final, "content", None) else ""
        if not content:
            return FALLBACK_REPLY

        # LangGraph 在步数不足时返回的内部提示，不能漏给用户
        if _NEED_MORE_STEPS in content:
            log.warning("ReAct 步数不足（recursion_limit=%d，最大轮数=%d），"
                        "已替换为面向用户的话术", limit, checker.max_steps)
            return STEP_LIMIT_REPLY

        return content
