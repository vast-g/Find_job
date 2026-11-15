"""Multi-Agent Supervisor：顶层 Agent 分解任务，Supervisor 调度子 Agent。

高并发保障（5 万人同时用如何不崩）：
1. Agent 无状态：会话状态全在 DB/外部存储，实例可水平扩展。
2. 子循环有界：每个子 Agent 都有 max_steps / timeout / budget。
3. 并发有界：asyncio.Semaphore 限制同时进行的 LLM 调用数。
4. 工具幂等：只读工具可缓存，写操作有唯一约束防重复。
5. 熔断降级：LLM 超限直接返回兜底话术，不拖垮队列。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from app.core.termination import TerminationChecker

# 全局 LLM 并发上限（可配），防雪崩
_LLM_SEMAPHORE = asyncio.Semaphore(50)


@dataclass
class SubAgentResult:
    name: str
    output: Any
    steps: int = 0
    error: str | None = None


class Supervisor:
    """调度多个子 Agent，各自有界。"""

    def __init__(self):
        self.checker = TerminationChecker()

    async def dispatch(self, plan: list[dict], ctx: dict) -> list[SubAgentResult]:
        """plan: [{"agent": "recommender", "kwargs": {...}}, ...]"""
        results: list[SubAgentResult] = []
        for task in plan:
            if self.checker.hit():
                results.append(SubAgentResult(name="supervisor", output=None, error="全局终止"))
                break
            agent_name = task["agent"]
            agent = _get_sub_agent(agent_name)
            async with _LLM_SEMAPHORE:
                try:
                    out = await asyncio.wait_for(
                        agent.run(ctx, **task.get("kwargs", {})),
                        timeout=self.checker.timeout_seconds,
                    )
                    results.append(SubAgentResult(name=agent_name, output=out))
                except asyncio.TimeoutError:
                    results.append(SubAgentResult(name=agent_name, output=None, error="timeout"))
                except Exception as e:  # noqa: BLE001
                    results.append(SubAgentResult(name=agent_name, output=None, error=str(e)))
        return results


def _get_sub_agent(name: str):
    from app.agents.sub_agents import SUB_AGENTS
    agent = SUB_AGENTS.get(name)
    if agent is None:
        raise ValueError(f"未知子 Agent: {name}")
    return agent
