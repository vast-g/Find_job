"""终止条件：ReAct 最大步数 10、超时 30s、超预算。"""
from __future__ import annotations

import time

from app.config import get_settings

FALLBACK_REPLY = "抱歉，这个问题处理超时了。您可以换个更具体的问法，或稍后再试。"

# 步数耗尽时的兜底话术。
# 不能直接返回 LangGraph 的内部提示 "Sorry, need more steps to process this request."
# —— 那是给开发者看的，漏给终端用户会显得系统坏了（实测确实漏过）。
STEP_LIMIT_REPLY = (
    "抱歉，这个问题需要多步检索才能完成，我暂时没能给出完整结果。"
    "建议把需求拆得更具体一些，例如直接说明**目标城市**和**岗位方向**，我可以更快给出推荐。"
)


class TerminationChecker:
    def __init__(self):
        s = get_settings()
        self.max_steps = s.max_react_steps
        self.timeout_seconds = s.timeout_seconds
        self.max_budget_usd = s.max_budget_usd
        self.start = time.monotonic()
        self.steps = 0

    def hit(self) -> bool:
        """是否触发终止。"""
        self.steps += 1
        if self.steps > self.max_steps:
            return True
        if time.monotonic() - self.start > self.timeout_seconds:
            return True
        return False

    def over_budget(self, cost_usd: float) -> bool:
        return cost_usd > self.max_budget_usd

    @property
    def reason(self) -> str:
        if self.steps > self.max_steps:
            return f"超过最大步数 {self.max_steps}"
        if time.monotonic() - self.start > self.timeout_seconds:
            return f"超过 {self.timeout_seconds}s 超时"
        return "超预算"
