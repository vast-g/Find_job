"""Process-local short-term history with the Redis store's public interface."""
from __future__ import annotations

from collections import defaultdict
from contextlib import asynccontextmanager
from contextvars import ContextVar
from time import monotonic
from uuid import uuid4

from app.config import get_settings
from app.memory.errors import SessionBusyError, SessionLeaseLostError
from app.memory.redis_store import StoredMessage


class InMemoryMessageStore:
    """All mutations run without awaits, making each operation task-atomic."""

    def __init__(self, max_turns: int | None = None):
        settings = get_settings()
        self.max_turns = max_turns if max_turns is not None else settings.short_term_turns
        if self.max_turns < 1:
            raise ValueError('max_turns must be positive')
        self.ttl = settings.redis_ttl
        self._data: dict[str, list[StoredMessage]] = defaultdict(list)
        self._counts: dict[str, int] = {}
        self._progress: dict[str, int] = {}
        self._expires: dict[str, float] = {}
        self._locks: dict[str, str] = {}
        self._lease: ContextVar[tuple[str, str] | None] = ContextVar('memory_session_lease', default=None)

    def _key(self, session_id: str) -> str:
        return f'chat:{session_id}'

    def _clear(self, key: str) -> None:
        self._data.pop(key, None)
        self._counts.pop(key, None)
        self._progress.pop(key, None)
        self._expires.pop(key, None)

    def _expire(self, key: str) -> None:
        deadline = self._expires.get(key)
        if deadline is not None and deadline <= monotonic():
            self._clear(key)

    def _check_lease(self, session_id: str) -> None:
        lease = self._lease.get()
        if lease is not None and lease[0] == session_id:
            if self._locks.get(session_id) != lease[1]:
                raise SessionLeaseLostError('Session lock ownership changed')

    def _append(self, session_id: str, messages: list[StoredMessage], completed: int) -> int:
        self._check_lease(session_id)
        key = self._key(session_id)
        self._expire(key)
        count = self._counts.get(key, len(self._data.get(key, [])) // 2) + completed
        self._data[key].extend(messages)
        self._data[key] = self._data[key][-self.max_turns * 2:]
        self._counts[key] = count
        if self.ttl:
            self._expires[key] = monotonic() + self.ttl
        else:
            self._expires.pop(key, None)
        return count

    async def add_turn(self, session_id: str, user_id: int,
                       user_content: str, assistant_content: str) -> int:
        return self._append(session_id, [StoredMessage('user', user_content),
                                        StoredMessage('assistant', assistant_content)], 1)

    async def add(self, session_id: str, user_id: int, role: str, content: str) -> None:
        self._append(session_id, [StoredMessage(role, content)], int(role == 'assistant'))

    async def recent(self, session_id: str, n: int | None = None) -> list[StoredMessage]:
        key = self._key(session_id)
        self._expire(key)
        n = n if n is not None else self.max_turns
        return list(self._data.get(key, [])[-n * 2:]) if n > 0 else []

    async def count_turns(self, session_id: str) -> int:
        key = self._key(session_id)
        self._expire(key)
        if key not in self._data:
            return 0
        return self._counts.setdefault(key, len(self._data[key]) // 2)

    async def summary_progress(self, session_id: str) -> int:
        key = self._key(session_id)
        self._expire(key)
        return self._progress.get(key, 0)

    async def mark_summarized(self, session_id: str, turn: int) -> None:
        self._check_lease(session_id)
        key = self._key(session_id)
        self._expire(key)
        if key in self._data:
            count = self._counts.setdefault(key, len(self._data[key]) // 2)
            self._progress[key] = max(self._progress.get(key, 0), min(count, max(0, int(turn))))

    async def delete_by_session(self, session_id: str) -> None:
        self._clear(self._key(session_id))

    @asynccontextmanager
    async def session_guard(self, session_id: str):
        if session_id in self._locks:
            raise SessionBusyError('Session already has an active request')
        token = uuid4().hex
        self._locks[session_id] = token
        context = self._lease.set((session_id, token))
        try:
            yield
            self._check_lease(session_id)
        finally:
            if self._locks.get(session_id) == token:
                del self._locks[session_id]
            self._lease.reset(context)
