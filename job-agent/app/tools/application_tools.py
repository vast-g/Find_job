"""工具：get_user_applications 获取当前用户投递记录（从 job_platform.application 联表读取）。"""
from __future__ import annotations

from langchain_core.tools import tool
from sqlalchemy import text

from app.core.context import get_current_user
from app.db.session import get_sessionmaker
from app.tools.registry import register_tool

_STATUS_TEXT = {
    1: "已投递",
    2: "已查看",
    3: "面试邀请",
    4: "已录用",
    5: "已拒绝",
}

_BASE_SQL = (
    "SELECT a.status, a.create_time, "
    "j.title AS job_title, c.name AS company_name "
    "FROM job_platform.application a "
    "LEFT JOIN job_platform.job j ON a.job_id = j.id "
    "LEFT JOIN job_platform.company c ON j.company_id = c.id "
)


@tool
async def get_user_applications(user_id: int | None = None) -> list[dict]:
    """获取当前请求用户的投递记录（含岗位名、公司名、状态）。"""
    context_uid = get_current_user()
    uid = context_uid if context_uid is not None else user_id

    # Negative signed IDs identify admin logins and have no candidate applications.
    # Return before creating a session so an admin request cannot query candidate data.
    if uid is None or uid <= 0:
        return []

    maker = get_sessionmaker()
    async with maker() as session:
        result = await session.execute(
            text(_BASE_SQL + "WHERE a.user_id = :uid ORDER BY a.create_time DESC"),
            {"uid": uid},
        )
        rows = result.mappings().all()

    applications = []
    for r in rows:
        d = dict(r)
        applications.append({
            "job": d.get("job_title"),
            "company": d.get("company_name"),
            "status": _STATUS_TEXT.get(d.get("status"), "未知"),
            "time": str(d.get("create_time")),
        })
    return applications


register_tool(get_user_applications)
