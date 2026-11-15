"""Redis 客户端：共享的 redis.asyncio 连接。"""
from __future__ import annotations

from functools import lru_cache

import redis.asyncio as aioredis

from app.config import get_settings


@lru_cache
def get_redis() -> aioredis.Redis:
    s = get_settings()
    return aioredis.Redis(
        host=s.redis_host,
        port=s.redis_port,
        db=s.redis_db,
        decode_responses=True,
        socket_connect_timeout=s.redis_socket_timeout,
        socket_timeout=s.redis_socket_timeout,
        max_connections=s.redis_max_connections,
        protocol=2,  # Redis 3.2 不支持 HELLO/RESP3，固定 RESP2
    )
