"""初始化数据库：创建 job_agent 库 + 建表。

用法：python -m app.db.init_db
"""
from __future__ import annotations

import asyncio

import aiomysql

from app.config import get_settings
from app.db.session import Base, get_engine


async def create_database() -> None:
    s = get_settings()
    conn = await aiomysql.connect(
        host=s.mysql_host, port=s.mysql_port, user=s.mysql_user, password=s.mysql_password
    )
    cur = await conn.cursor()
    await cur.execute(
        f"CREATE DATABASE IF NOT EXISTS `{s.mysql_db}` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci"
    )
    await cur.close()
    conn.close()


async def create_tables() -> None:
    # 导入 models 使 Base.metadata 注册所有表
    import app.db.models  # noqa: F401
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()


async def main() -> None:
    await create_database()
    await create_tables()
    print("数据库初始化完成")


if __name__ == "__main__":
    asyncio.run(main())
