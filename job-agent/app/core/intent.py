"""意图识别：把用户输入归入 5 类意图，用 LangChain structured output。"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.llm.factory import get_structured_model
from langchain_core.messages import HumanMessage, SystemMessage

INTENT_PROMPT = """你是求职助手的意图识别器。把用户输入归入以下 3 类之一，并抽取关键信息：
- recommend: 岗位推荐（找岗位/推荐/适合我）
- resume_opt: 简历优化（改简历/简历建议/对比岗位要求）
- qa: 求职问答（面试技巧/行业知识/备考/流程答疑）"""


class IntentResult(BaseModel):
    intent: str = Field(description="recommend/resume_opt/qa")
    slots: dict = Field(default_factory=dict, description="抽取的城市/关键词/岗位等")


async def recognize_intent(query: str, history: list[str] | None = None) -> dict:
    # 用 get_structured_model()：结构化输出会强制 tool_choice，
    # 而 DeepSeek 思考模式与 tool_choice="required" 互斥，会直接 400。
    # 这是 Agent 链路的第一步，它一挂整条用例就全废（实测 75/75 失败）。
    model = get_structured_model()
    structured = model.with_structured_output(IntentResult, method="function_calling")
    msgs = [SystemMessage(content=INTENT_PROMPT)]
    if history:
        msgs.append(HumanMessage(content="历史：\n" + "\n".join(history)))
    msgs.append(HumanMessage(content=query))
    result = await structured.ainvoke(msgs)
    if isinstance(result, IntentResult):
        return {"intent": result.intent, "slots": result.slots}
    return {"intent": "qa", "slots": {}}
