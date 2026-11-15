"""短期记忆后端工厂：按配置返回 Redis 版或进程内版。

统一入口，避免调用方各自 `RedisMessageStore(get_redis())` 而把 Redis 变成硬依赖。

    from app.memory.factory import get_memory_store
    store = get_memory_store()
"""
from __future__ import annotations

from functools import lru_cache

from app.config import get_settings


@lru_cache
def get_memory_store():
    """按 MEMORY_BACKEND 返回单例。

    * `memory` —— 进程内（评测 / 容器 / 无 Redis 环境）
    * `redis`  —— 生产默认

    Redis 版采用**惰性导入**：未装 redis 客户端包、或选了 memory 后端时，
    完全不触碰 redis 相关模块。
    """
    s = get_settings()
    if (s.memory_backend or "redis").lower() == "memory":
        from app.memory.memory_store import InMemoryMessageStore

        return InMemoryMessageStore()

    from app.db.redis_client import get_redis
    from app.memory.redis_store import RedisMessageStore

    return RedisMessageStore(get_redis())


def reset_memory_store() -> None:
    """清缓存（测试或切换后端时使用）。"""
    get_memory_store.cache_clear()
