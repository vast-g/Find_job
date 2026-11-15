"""工具：get_user_resume 获取当前用户简历（从 job_platform.resume 读取）。"""
from __future__ import annotations

from langchain_core.tools import tool
from sqlalchemy import text

from app.core.context import get_current_user
from app.db.session import get_sessionmaker
from app.tools.registry import register_tool

# 只取有业务含义的字段，避免把 id/create_time 等无意义字段喂给模型
_RESUME_FIELDS = (
    "name, education, school, major, age, skills, summary, experience, "
    "education_experience, project_experience, campus_experience, job_status, "
    "expect_position, expect_city, expect_salary, expect_industry, "
    "club_experience, honors, certificates"
)


def _clean_row(row: dict) -> dict:
    """把数据库行转成干净字典：skills 拆成列表，过滤空值。"""
    out: dict = {}
    for key, value in row.items():
        if value is None:
            continue
        if key == "skills" and isinstance(value, str) and value.strip():
            out[key] = [s.strip() for s in value.split(",") if s.strip()]
        elif isinstance(value, str) and value.strip():
            out[key] = value.strip()
        elif not isinstance(value, str):
            out[key] = value
    return out


@tool
async def get_user_resume(user_id: int | None = None) -> dict:
    """获取当前请求用户的默认简历。"""
    context_uid = get_current_user()
    uid = context_uid if context_uid is not None else user_id

    # Negative signed IDs identify admin logins and have no candidate resume.
    # Return before creating a session so an admin request cannot query candidate data.
    if uid is None or uid <= 0:
        return {}

    sql = (f"SELECT {_RESUME_FIELDS} FROM job_platform.resume "
           "WHERE user_id = :uid ORDER BY is_default DESC, create_time DESC LIMIT 1")
    maker = get_sessionmaker()
    async with maker() as session:
        result = await session.execute(text(sql), {"uid": uid})
        row = result.mappings().first()

    return _clean_row(dict(row)) if row is not None else {}


register_tool(get_user_resume)
