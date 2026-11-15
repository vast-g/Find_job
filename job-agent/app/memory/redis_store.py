"""Atomic Redis short-term history, cumulative metadata, and renewable leases.

Keys retain the legacy ``chat:{passed session_id}`` spelling. Lua only uses
commands available in Redis 3.2; history and metadata expire together.
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import uuid4

import redis.asyncio as aioredis

from app.config import get_settings
from app.memory.errors import SessionBusyError, SessionLeaseLostError


@dataclass
class StoredMessage:
    role: str
    content: str


@dataclass
class _Lease:
    session_id: str
    token: str
    lost: bool = False


# A token is checked in the SAME operation as the append, fencing stale writers.
_APPEND = """
if ARGV[1] ~= '' and redis.call('GET', KEYS[3]) ~= ARGV[1] then return -1 end
if redis.call('EXISTS', KEYS[1]) == 0 then redis.call('DEL', KEYS[2]) end
local turns = tonumber(redis.call('HGET', KEYS[2], 'turns'))
if not turns then turns = math.floor(redis.call('LLEN', KEYS[1]) / 2) end
redis.call('RPUSH', KEYS[1], ARGV[4])
if ARGV[5] ~= '' then redis.call('RPUSH', KEYS[1], ARGV[5]) end
redis.call('LTRIM', KEYS[1], -tonumber(ARGV[2]), -1)
turns = turns + tonumber(ARGV[6])
redis.call('HSET', KEYS[2], 'turns', turns)
if tonumber(ARGV[3]) > 0 then
    redis.call('EXPIRE', KEYS[1], ARGV[3])
    redis.call('EXPIRE', KEYS[2], ARGV[3])
else
    redis.call('PERSIST', KEYS[1])
    redis.call('PERSIST', KEYS[2])
end
return turns
"""

# Reads migrate list-only histories; checkpoints neither extend history's life
# nor recreate a chat that expired while summarization was running.
_METADATA = """
if ARGV[3] ~= '' and redis.call('GET', KEYS[3]) ~= ARGV[3] then return -1 end
if redis.call('EXISTS', KEYS[1]) == 0 then
    redis.call('DEL', KEYS[2])
    return 0
end
local turns = tonumber(redis.call('HGET', KEYS[2], 'turns'))
if not turns then
    turns = math.floor(redis.call('LLEN', KEYS[1]) / 2)
    redis.call('HSET', KEYS[2], 'turns', turns)
end
local progress = tonumber(redis.call('HGET', KEYS[2], 'summarized')) or 0
if ARGV[1] == 'mark' then
    progress = math.max(progress, math.min(turns, tonumber(ARGV[2])))
    redis.call('HSET', KEYS[2], 'summarized', progress)
end
local ttl = redis.call('PTTL', KEYS[1])
if ttl >= 0 then redis.call('PEXPIRE', KEYS[2], ttl)
else redis.call('PERSIST', KEYS[2]) end
if ARGV[1] == 'count' then return turns else return progress end
"""
_RENEW = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('EXPIRE', KEYS[1], ARGV[2])
end
return 0
"""
_RELEASE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


class RedisMessageStore:
    def __init__(self, redis: aioredis.Redis, max_turns: int | None = None):
        settings = get_settings()
        self.redis = redis
        self.max_turns = max_turns if max_turns is not None else settings.short_term_turns
        if self.max_turns < 1:
            raise ValueError('max_turns must be positive')
        self.ttl = settings.redis_ttl
        self._lease: ContextVar[_Lease | None] = ContextVar('redis_session_lease', default=None)

    def _key(self, session_id: str) -> str:
        return f'chat:{session_id}'

    def _token(self, session_id: str) -> str:
        lease = self._lease.get()
        if lease is not None and lease.session_id == session_id:
            if lease.lost:
                raise SessionLeaseLostError('Session lease was lost')
            return lease.token
        return ''

    async def _append(self, session_id: str, first: str, second: str, turns: int) -> int:
        key = self._key(session_id)
        result = int(await self.redis.eval(
            _APPEND, 3, key, key + ':meta', key + ':lock',
            self._token(session_id), self.max_turns * 2, self.ttl or 0,
            first, second, turns,
        ))
        if result < 0:
            lease = self._lease.get()
            if lease is not None and lease.session_id == session_id:
                lease.lost = True
            raise SessionLeaseLostError('Session lock ownership changed')
        return result

    async def add_turn(self, session_id: str, user_id: int,
                       user_content: str, assistant_content: str) -> int:
        return await self._append(
            session_id,
            json.dumps({'role': 'user', 'content': user_content}, ensure_ascii=False),
            json.dumps({'role': 'assistant', 'content': assistant_content}, ensure_ascii=False),
            1,
        )

    async def add(self, session_id: str, user_id: int, role: str, content: str) -> None:
        # Legacy callers append separately: only the assistant completes a turn.
        await self._append(session_id, json.dumps(
            {'role': role, 'content': content}, ensure_ascii=False), '', int(role == 'assistant'))

    async def recent(self, session_id: str, n: int | None = None) -> list[StoredMessage]:
        n = n if n is not None else self.max_turns
        if n <= 0:
            return []
        items = await self.redis.lrange(self._key(session_id), -n * 2, -1)
        result: list[StoredMessage] = []
        for item in items:
            try:
                data = json.loads(item)
            except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
                continue
            if isinstance(data, dict):
                result.append(StoredMessage(role=data.get('role', 'user'), content=data.get('content', '')))
        return result

    async def _metadata(self, session_id: str, operation: str, turn: int = 0) -> int:
        key = self._key(session_id)
        result = int(await self.redis.eval(_METADATA, 3, key, key + ':meta', key + ':lock',
                                           operation, turn, self._token(session_id)))
        if result < 0:
            lease = self._lease.get()
            if lease is not None and lease.session_id == session_id:
                lease.lost = True
            raise SessionLeaseLostError('Session lock ownership changed')
        return result

    async def count_turns(self, session_id: str) -> int:
        return await self._metadata(session_id, 'count')

    async def summary_progress(self, session_id: str) -> int:
        return await self._metadata(session_id, 'progress')

    async def mark_summarized(self, session_id: str, turn: int) -> None:
        await self._metadata(session_id, 'mark', max(0, int(turn)))

    async def delete_by_session(self, session_id: str) -> None:
        key = self._key(session_id)
        await self.redis.delete(key, key + ':meta')

    async def _heartbeat(self, lease: _Lease, ttl: int) -> None:
        try:
            while True:
                await asyncio.sleep(ttl / 3)
                if not await self.redis.eval(_RENEW, 1, self._key(lease.session_id) + ':lock', lease.token, ttl):
                    lease.lost = True
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            # Fail closed: the next write and successful guard exit both reject.
            lease.lost = True

    @asynccontextmanager
    async def session_guard(self, session_id: str):
        ttl = max(1, int(get_settings().memory_lock_ttl))
        lease = _Lease(session_id, uuid4().hex)
        lock_key = self._key(session_id) + ':lock'
        if not await self.redis.set(lock_key, lease.token, nx=True, ex=ttl):
            raise SessionBusyError('Session already has an active request')
        context = self._lease.set(lease)
        heartbeat = asyncio.create_task(self._heartbeat(lease, ttl))
        body_failed = False
        try:
            yield
        except BaseException:
            body_failed = True
            raise
        finally:
            heartbeat.cancel()
            try:
                await asyncio.gather(heartbeat, return_exceptions=True)
                released = await self.redis.eval(_RELEASE, 1, lock_key, lease.token)
                if not released:
                    lease.lost = True
            except asyncio.CancelledError:
                raise
            except Exception:
                lease.lost = True
                if not body_failed:
                    raise SessionLeaseLostError('Could not release session lease') from None
            finally:
                self._lease.reset(context)
            if lease.lost and not body_failed:
                raise SessionLeaseLostError('Session lease was lost')
