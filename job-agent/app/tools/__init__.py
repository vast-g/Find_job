"""工具包：导入各工具模块触发自注册，并暴露查询接口。"""
from app.tools.registry import get_tool, get_tools, get_tools_by_name, register_tool

# 导入触发自注册
from app.tools import (  # noqa: E402,F401
    application_tools,
    job_tools,
    knowledge_tools,
    resume_tools,
)

__all__ = ["get_tool", "get_tools", "get_tools_by_name", "register_tool"]
