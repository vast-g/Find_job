"""Query Rewrite：用 LLM 把口语/指代/多轮 query 改写成检索友好查询（支持多查询扩展）。"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.llm.factory import get_structured_model
from langchain_core.messages import SystemMessage, HumanMessage


class QueryRewriteResult(BaseModel):
    queries: list[str] = Field(description="1-3 个检索查询词")


REWRITE_PROMPT = """你是求职检索改写器。把用户问题改写成 1-3 个适合检索的查询词。
要求：补全指代；去掉口语寒暄；保留城市/行业/薪资约束。"""


async def rewrite_query(query: str, context: list[str] | None = None) -> list[str]:
    # 结构化输出强制 tool_choice，与 DeepSeek 思考模式互斥，故用关闭思考的实例
    model = get_structured_model()
    structured = model.with_structured_output(QueryRewriteResult, method="function_calling")
    msgs = [SystemMessage(content=REWRITE_PROMPT)]
    if context:
        msgs.append(HumanMessage(content="对话历史：\n" + "\n".join(context)))
    msgs.append(HumanMessage(content=f"用户问题：{query}"))

    result = await structured.ainvoke(msgs)
    queries = result.queries if isinstance(result, QueryRewriteResult) else []
    return [q for q in queries if q] or [query]
