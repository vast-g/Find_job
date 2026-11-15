"""LangChain 回调处理器：采集 token / 工具 / 检索，写 agent_trace。

## 改造原因（实测发现的缺陷）

原实现直接在回调里 `repo.add(...)` → `session.add() + flush()`，
而复用请求的**主 session**。但 LangChain 回调是在 ORM flush 过程中触发的，
此时再 add+flush 会抛：

    InvalidRequestError('Session is already flushing')

后果是 **`on_tool_end` 每次都被吞掉，工具调用痕迹根本写不进 agent_trace**，
"基于 Agent Trace 的评测"就少了最关键的证据链。

## 现在怎么做

1. **内存缓冲**：回调只把待写行 append 到 `self._pending`，不碰数据库；
2. **收尾统一落库**：`aflush()` 用**独立 session** 一次性写入并 commit。

这样既避开 flush 冲突，也让"埋点失败"不再影响主流程；
独立 session 还带来一个好处：**请求失败了，它的 trace 依然留得下来**。

另外补上了工具名：原来 `on_tool_end` 只记输出不记工具名，
`tool_name` 列基本是空的，Tool Accuracy 无法从 trace 还原。
"""
from __future__ import annotations

import json
import logging
import time

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from app.core.stats import RunStats
from app.db.models import AgentTrace

log = logging.getLogger("app.observability.callback")


class ObservabilityCallbackHandler(BaseCallbackHandler):
    def __init__(self, stats: RunStats, session, request_id: str,
                 session_id: str | None, user_id: int | None):
        self.stats = stats
        self.session = session
        self.request_id = request_id
        self.session_id = session_id
        self.user_id = user_id
        self._step = 0
        self._current_tool: str | None = None
        self._llm_name: str | None = None
        self._last_prompt: str | None = None
        self._tool_started_at: dict[str, float] = {}
        # 待落库的 trace 行（内存缓冲，收尾时统一写）
        self._pending: list[dict] = []

    # ---- 缓冲 ----
    def _enqueue(self, node: str, input_data: str | None, output: str | None,
                 model: str | None = None, error: str | None = None,
                 cost_time_ms: int | None = None) -> None:
        self._step += 1
        self._pending.append({
            "request_id": self.request_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "step": self._step,
            "node": node,
            "input": input_data[:2000] if input_data else None,
            "output": output[:2000] if output else None,
            "model_used": model,
            "error": error,
            "cost_time_ms": cost_time_ms,
        })

    async def aflush(self) -> int:
        """把缓冲的 trace 行用独立 session 落库。返回写入行数。"""
        if not self._pending:
            return 0
        rows, self._pending = self._pending, []
        try:
            # 独立 session：不与请求事务竞争，也不会因主流程回滚而丢
            from app.db.session import get_sessionmaker

            maker = get_sessionmaker()
            async with maker() as s:
                for r in rows:
                    s.add(AgentTrace(**r))
                await s.commit()
            return len(rows)
        except Exception as exc:  # noqa: BLE001 - trace 失败不应影响业务
            log.warning("Agent Trace 落库失败（已丢弃 %d 行）：%s: %s",
                        len(rows), type(exc).__name__, exc)
            return 0

    # ---- LLM ----
    # 注意：这里刻意全部用**同步**方法。
    # LangChain 的回调分派对 async 变体（aon_*）与同步变体（on_*）有不同路径，
    # 实测把 on_tool_start 写成 `async def` 会导致它**根本不被调用**
    # （工具名恒为空、tool_start 行完全缺失）。缓冲本身不需要 await，
    # 因此同步实现最可靠；唯一的异步落库由 aflush() 显式触发。
    def on_llm_start(self, serialized, prompts, **kwargs) -> None:
        self._llm_name = serialized.get("name") or (kwargs.get("invocation_params") or {}).get("model")
        self._last_prompt = str(prompts[-1])[:2000] if prompts else None

    def on_llm_end(self, response: LLMResult, **kwargs) -> None:
        self.stats.add_usage(self._extract_usage(response))
        self._enqueue("llm", self._last_prompt, self._first_text(response), self._llm_name)

    def on_llm_error(self, error: BaseException, **kwargs) -> None:
        self._enqueue("llm", self._last_prompt, None, self._llm_name,
                      error=f"{type(error).__name__}: {error}")

    # ---- Tool ----
    def on_tool_start(self, serialized, input_str, **kwargs) -> None:
        self._current_tool = serialized.get("name")
        self._tool_started_at[self._current_tool or ""] = time.perf_counter()
        self.stats.add_tool_call(self._current_tool or "")
        # 工具名写进 input，保证 trace 能还原"调了哪个工具、传了什么参数"
        self._enqueue("tool_start", str(self._current_tool), str(input_str)[:2000])

    def on_tool_end(self, output, **kwargs) -> None:
        name = self._current_tool or ""
        started = self._tool_started_at.get(name)
        cost_ms = int((time.perf_counter() - started) * 1000) if started else None

        # 记录**所有**工具的返回正文，而不只是 search_knowledge。
        # 为什么关键：忠实度判定要拿"回答所依据的材料"去核对每一句陈述。
        # 岗位推荐/简历优化类回答依据的是 get_user_resume / search_jobs 的返回，
        # 若只记知识库检索结果，这些用例就会"没有上下文"，
        # 忠实度被直接判为 0（假阴性，严重拉低指标）。
        text = output.content if hasattr(output, "content") else output
        if isinstance(text, str):
            self.stats.add_tool_output(text)

        if name == "search_knowledge":
            self._record_docs(output)
        self._enqueue("tool", name, str(output)[:2000], cost_time_ms=cost_ms)

    def on_tool_error(self, error: BaseException, **kwargs) -> None:
        self._enqueue("tool", self._current_tool, None, error=f"{type(error).__name__}: {error}")

    # ---- 内部 ----
    def _extract_usage(self, response: LLMResult) -> dict | None:
        tu = (response.llm_output or {}).get("token_usage") or {}
        if tu.get("prompt_tokens") is not None or tu.get("completion_tokens") is not None:
            return {"prompt_tokens": tu.get("prompt_tokens", 0),
                    "completion_tokens": tu.get("completion_tokens", 0)}
        for gen_list in response.generations:
            for gen in gen_list:
                um = getattr(getattr(gen, "message", None), "usage_metadata", None)
                if um:
                    return {
                        "prompt_tokens": um.get("input_tokens", um.get("prompt_tokens", 0)),
                        "completion_tokens": um.get("output_tokens", um.get("completion_tokens", 0)),
                    }
        return None

    def _first_text(self, response: LLMResult) -> str | None:
        for gen_list in response.generations:
            for gen in gen_list:
                if getattr(gen, "text", None):
                    return gen.text
        return None

    def _record_docs(self, output) -> None:
        """从 search_knowledge 的工具返回里提取检索文档，供 Recall@K / 忠实度使用。"""
        try:
            if hasattr(output, "content"):
                output = output.content
            docs = json.loads(output) if isinstance(output, str) else output
            if isinstance(docs, list):
                self.stats.add_retrieved_docs(docs)
        except Exception as exc:  # noqa: BLE001 - 不再静默，便于定位
            log.debug("检索文档解析失败（不影响主流程）：%s", exc)
