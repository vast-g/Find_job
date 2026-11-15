"""工具注册表：收集所有 @tool 工具。

各工具模块在底部调用 register_tool() 自注册；
app/tools/__init__.py 统一 import 这些模块触发注册。
"""
from __future__ import annotations

from langchain_core.tools import BaseTool

_ALL_TOOLS: dict[str, BaseTool] = {}


def register_tool(t: BaseTool) -> None:
    _ALL_TOOLS[t.name] = t


def get_tool(name: str) -> BaseTool | None:
    return _ALL_TOOLS.get(name)


def get_tools() -> list[BaseTool]:
    return list(_ALL_TOOLS.values())


def get_tools_by_name(names: list[str]) -> list[BaseTool]:
    return [t for n in names if (t := _ALL_TOOLS.get(n))]
