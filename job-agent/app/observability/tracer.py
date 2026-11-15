"""可观测性：每一步执行记录到 agent_trace 表。

用法：
    tracer = Tracer(session, request_id)
    with tracer.step("intent", input_text) as t:
        ...  # 执行
        t.set_output(...)
"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentTrace
from app.db.repositories import TraceRepository


class Tracer:
    def __init__(self, session: AsyncSession, request_id: str, session_id: str | None = None, user_id: int | None = None):
        self.session = session
        self.request_id = request_id
        self.session_id = session_id
        self.user_id = user_id
        self._step = 0
        self.repo = TraceRepository(session)

    def _next_step(self) -> int:
        self._step += 1
        return self._step

    @asynccontextmanager
    async def step(self, node: str, input_data: Any = None, model_used: str | None = None):
        step = self._next_step()
        start = time.perf_counter()
        holder: dict[str, Any] = {}
        try:
            yield holder
        finally:
            cost_ms = int((time.perf_counter() - start) * 1000)
            await self.repo.add(AgentTrace(
                request_id=self.request_id,
                session_id=self.session_id,
                user_id=self.user_id,
                step=step,
                node=node,
                input=str(input_data)[:2000] if input_data is not None else None,
                output=str(holder.get("output"))[:2000] if holder.get("output") is not None else None,
                model_used=model_used or holder.get("model_used"),
                cost_time_ms=cost_ms,
                error=holder.get("error"),
            ))

    def set_output(self, holder: dict, value: Any) -> None:
        holder["output"] = value

    def set_model(self, holder: dict, model: str) -> None:
        holder["model_used"] = model

    def set_error(self, holder: dict, err: str) -> None:
        holder["error"] = err
