"""短期记忆：实现 LangChain BaseChatMessageHistory。

MySQL 版保留（MySQLChatMessageHistory）；新增 Redis 版（RedisChatMessageHistory）。
与长期记忆（user_profile）解耦：短期只存原话，不摘要、不改写。
"""
from __future__ import annotations

from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from app.db.models import Message
from app.db.repositories import MessageRepository
from app.memory.redis_store import RedisMessageStore


def _to_lc(m) -> BaseMessage:
    if m.role == "assistant":
        return AIMessage(content=m.content or "")
    if m.role == "system":
        return SystemMessage(content=m.content or "")
    if m.role == "tool":
        return ToolMessage(content=m.content or "", tool_call_id="")
    return HumanMessage(content=m.content or "")


def _from_lc(msg: BaseMessage) -> tuple[str, str]:
    role = msg.type
    if role == "ai":
        role = "assistant"
    elif role == "human":
        role = "user"
    return role, msg.content if isinstance(msg.content, str) else str(msg.content)


class MySQLChatMessageHistory(BaseChatMessageHistory):
    """基于 MySQL message 表的会话历史，保留最近 max_turns 轮。"""

    def __init__(self, session_id: str, user_id: int, repo: MessageRepository, max_turns: int = 10):
        self.session_id = session_id
        self.user_id = user_id
        self.repo = repo
        self.max_turns = max_turns
        self._buffer: list[BaseMessage] = []

    @property
    def messages(self) -> list[BaseMessage]:
        return list(self._buffer)

    def add_messages(self, messages: list[BaseMessage]) -> None:
        self._buffer.extend(messages)

    async def aget_messages(self) -> list[BaseMessage]:
        rows = await self.repo.recent(self.session_id, self.max_turns)
        return [_to_lc(m) for m in rows]

    def clear(self) -> None:
        self._buffer.clear()

    async def aclear(self) -> None:
        self._buffer.clear()
        await self.repo.delete_by_session(self.session_id)

    async def aadd_messages(self, messages: list[BaseMessage]) -> None:
        turn = await self.repo.count_turns(self.session_id) + 1
        for msg in messages:
            role, content = _from_lc(msg)
            await self.repo.add(self.session_id, self.user_id, role, content, turn)


class RedisChatMessageHistory(BaseChatMessageHistory):
    """基于 Redis 的会话历史，保留最近 max_turns 轮（由 RedisMessageStore 控制）。"""

    def __init__(self, session_id: str, user_id: int, store: RedisMessageStore):
        self.session_id = session_id
        self.user_id = user_id
        self.store = store
        self._buffer: list[BaseMessage] = []

    @property
    def messages(self) -> list[BaseMessage]:
        return list(self._buffer)

    def add_messages(self, messages: list[BaseMessage]) -> None:
        self._buffer.extend(messages)

    def clear(self) -> None:
        self._buffer.clear()

    async def aget_messages(self) -> list[BaseMessage]:
        rows = await self.store.recent(self.session_id)
        return [_to_lc(m) for m in rows]

    async def aclear(self) -> None:
        self._buffer.clear()
        await self.store.delete_by_session(self.session_id)

    async def aadd_messages(self, messages: list[BaseMessage]) -> None:
        if not messages:
            return
        # 此适配器只持久化完整的外层问答，不持久化 ReAct 中间工具消息。
        if len(messages) % 2:
            raise ValueError("短期记忆需要完整的 user/assistant 对话轮次")
        pairs = []
        for i in range(0, len(messages), 2):
            user_role, user_content = _from_lc(messages[i])
            assistant_role, assistant_content = _from_lc(messages[i + 1])
            if user_role != "user" or assistant_role != "assistant":
                raise ValueError("短期记忆消息顺序必须是 user 然后 assistant")
            pairs.append((user_content, assistant_content))
        for user_content, assistant_content in pairs:
            await self.store.add_turn(self.session_id, self.user_id, user_content, assistant_content)
