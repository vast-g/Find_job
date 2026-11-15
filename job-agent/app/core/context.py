"""请求级上下文：让工具拿到"当前用户"，而不用让模型去猜。

## 解决什么问题

`get_user_resume(user_id)` 原来是**必填参数**，但模型根本无从得知用户的 id ——
用户说的是"帮我看看我的简历"，句子里没有任何 id 信息。
于是模型只能反问「请提供您的用户 ID」，把一个本可自动完成的流程
变成了一次多余交互。

实测：75 条评测样本里，岗位推荐与简历优化类用例大量败在这里
（期望调用 `get_user_resume`，实际要么一个工具没调，要么只调了 `search_jobs`）。

## 为什么用 contextvars

工具是**并发执行**的（评测并发 4，线上也可能并发），
用模块级全局变量会串号。`contextvars` 天然按协程隔离，
且在 `asyncio.gather` 的子任务里能正确继承。

## 取值优先级

当前请求身份优先于模型传入的 user_id；无请求上下文时仅允许显式正数 ID。
缺少身份时不读取任何用户数据。负数 ID 属于管理员助手命名空间，不查询求职用户资料。
"""
from __future__ import annotations

from contextvars import ContextVar, Token

_current_user_id: ContextVar[int | None] = ContextVar("dsh_current_user_id", default=None)


def set_current_user(user_id: int | None) -> Token:
    """在请求入口设置当前用户，返回 token 供恢复。"""
    return _current_user_id.set(user_id)


def get_current_user() -> int | None:
    """读取当前请求的用户 id；不在请求上下文中时返回 None。"""
    return _current_user_id.get()


def reset_current_user(token: Token) -> None:
    """恢复设置前的状态（避免上下文泄漏到后续请求）。"""
    try:
        _current_user_id.reset(token)
    except (ValueError, LookupError):
        # token 属于别的上下文（例如跨协程误用），忽略即可
        pass
