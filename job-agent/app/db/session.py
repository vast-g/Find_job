"""SQLAlchemy async 会话与引擎（懒加载，避免 import 时强依赖 DB 驱动）。"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    pass


_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _get_engine():
    """懒加载引擎：首次真正访问数据库时才创建连接池。"""
    global _engine, _sessionmaker
    if _engine is None:
        _engine = create_async_engine(
            get_settings().mysql_url, pool_pre_ping=True, pool_size=10, max_overflow=20
        )
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    return _engine, _sessionmaker


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return _get_engine()[1]


def get_engine():
    """暴露引擎，供建表/迁移等场景使用。"""
    return _get_engine()[0]


async def get_db():
    """FastAPI 依赖：每次请求一个会话。"""
    maker = get_sessionmaker()
    async with maker() as session:
        yield session
