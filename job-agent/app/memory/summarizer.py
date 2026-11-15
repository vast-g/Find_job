"""摘要生成：每 N 轮对话触发一次，用 LLM 结构化提取长期记忆。

触发时机：当前会话 turn 数为 summary_interval 的整数倍。
写入前经过 filter 过滤；提取出摘要 + 目标/偏好/技能/简历要点后写入 user_profile。
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.config import get_settings
from langchain_core.messages import HumanMessage, SystemMessage

from app.db.repositories import ProfileRepository
from app.llm.factory import get_chat_model, get_structured_model
from app.memory.filter import should_keep

EXTRACT_PROMPT = """根据下面这段对话，提炼可沉淀到用户长期记忆的信息。
要求：
1. 只保留跨会话仍有价值的信息，去掉寒暄和一次性内容，不要包含任何敏感凭证。
2. summary 用 2-4 句话概括这段对话中可沉淀的要点。
3. 其余字段只有在对话中明确出现时才填，没出现就置 null/空：
   - goals：用户的求职目标
   - preferences：偏好，形如 {"city": "北京", "salary": "15-25k", "industry": "金融"}
   - skills：技能列表，如 ["Java", "Python"]
   - resume_summary：从对话中提炼出的简历要点
"""


class ProfileExtraction(BaseModel):
    summary: str = Field(description="2-4 句跨会话摘要")
    goals: str | None = None
    preferences: dict | None = None
    skills: list[str] | None = None
    resume_summary: str | None = None


async def maybe_summarize(
    session_id: str,
    user_id: int,
    msg_repo,  # 短期记忆仓库：RedisMessageStore 或 MessageRepository，需提供 recent/count_turns
    profile_repo: ProfileRepository,
    *,
    defer_checkpoint: bool = False,
) -> str | None:
    """处理自上次进度以来的新对话；调用方可延迟到 SQL 提交后再推进进度。"""
    interval = get_settings().summary_interval
    turns = await msg_repo.count_turns(session_id)
    previous = await msg_repo.summary_progress(session_id)
    delta = turns - previous
    if interval <= 0 or delta < interval:
        return None

    # 摘要失败后的补做允许跨过整除边界，但最多读取尚保留的窗口。
    available = getattr(msg_repo, "max_turns", get_settings().short_term_turns)
    recent = await msg_repo.recent(session_id, min(delta, available))
    dialogue = "\n".join(f"{m.role}: {m.content}" for m in recent)

    async def checkpoint() -> None:
        if not defer_checkpoint:
            await msg_repo.mark_summarized(session_id, turns)

    # 没有长期价值也算已处理，避免反复对同一段内容调用过滤模型。
    if not await should_keep(dialogue):
        await checkpoint()
        return None

    # 结构化输出强制 tool_choice，与 DeepSeek 思考模式互斥，故用关闭思考的实例
    model = get_structured_model()
    structured = model.with_structured_output(ProfileExtraction, method="function_calling")
    result = await structured.ainvoke([
        SystemMessage(content=EXTRACT_PROMPT),
        HumanMessage(content=dialogue),
    ])

    if not isinstance(result, ProfileExtraction) or not (result.summary or "").strip():
        await checkpoint()
        return None

    await profile_repo.upsert_profile(
        user_id,
        summary=result.summary.strip(),
        goals=result.goals,
        preferences=result.preferences,
        skills=result.skills,
        resume_summary=result.resume_summary,
    )
    await checkpoint()
    return result.summary
