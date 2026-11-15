"""编排层：根据意图选择执行模式。

当前业务下 3 类意图都是「路径未知、需动态决策」型，统一走 ReAct。

划分标准（供后续扩展）：
- 步骤固定、合规强、需幂等 -> Workflow（确定性流程）
- 路径未知、需多轮动态决策 -> ReAct

现状：投递进度已改为邮箱通知、模拟面试已砍掉，暂无「步骤固定」的任务，
因此暂时只有 ReAct 分支；未来若有固定流程任务再引入 Workflow。
"""
from __future__ import annotations

from dataclasses import dataclass

INTENT_ROUTING = {
    "recommend": "react",
    "resume_opt": "react",
    "qa": "react",
}


@dataclass
class RouteDecision:
    mode: str
    intent: str
    handler: str | None = None


def route(intent: str) -> RouteDecision:
    mode = INTENT_ROUTING.get(intent, "react")
    return RouteDecision(mode=mode, intent=intent)
