"""摘要错误修复：三重机制。

1. 用户反馈：前端「有效/无效」按钮 -> /memory/feedback 接口，落 summary_feedback 表。
2. 定期评测：离线脚本扫 summary_feedback，发现无效摘要占比高的用户，回溯用原始对话重新生成。
3. 手动修正：/memory/correct 接口，人工直接覆盖摘要。
"""
from __future__ import annotations

from langchain_core.messages import HumanMessage

from app.db.repositories import FeedbackRepository, ProfileRepository
from app.llm.factory import get_chat_model

REPAIR_PROMPT = """下面是一条被用户标记为「无效」的摘要，以及当时的原始对话。
请重新生成一条更准确的摘要（2-4 句话，中文，只保留长期价值信息）。

错误摘要：{bad_summary}

原始对话：
{dialogue}

新摘要："""


async def record_feedback(
    user_id: int,
    summary_text: str | None,
    rating: int,
    correction: str | None,
    feedback_repo: FeedbackRepository,
) -> None:
    await feedback_repo.add(user_id, summary_text, rating, correction)


async def manual_correct(user_id: int, new_summary: str, profile_repo: ProfileRepository) -> None:
    """手动修正接口：直接覆盖摘要。"""
    await profile_repo.upsert_summary(user_id, new_summary)


async def regenerate_from_dialogue(
    bad_summary: str,
    dialogue: str,
    user_id: int,
    profile_repo: ProfileRepository,
) -> str:
    """评测/回溯时：用原始对话重新生成摘要并覆盖。"""
    m = get_chat_model()
    resp = await m.ainvoke([
        HumanMessage(content=REPAIR_PROMPT.format(bad_summary=bad_summary, dialogue=dialogue)),
    ])
    new_summary = (resp.content or "").strip()
    if new_summary:
        await profile_repo.upsert_summary(user_id, new_summary)
    return new_summary


async def offline_review(feedback_repo, profile_repo, msg_repo) -> int:
    """定期评测脚本入口：扫描无效反馈，回溯重新生成，返回修复条数。

    生产可由 cron / CI 定期调用。
    """
    # 伪代码示例：真实实现需从 feedback 表连出原始对话
    repaired = 0
    # rows = await feedback_repo.list_bad_ratings()
    # for row in rows:
    #     dialogue = await msg_repo.get_dialogue_by_summary_time(row.user_id, row.create_time)
    #     await regenerate_from_dialogue(row.summary_text, dialogue, row.user_id, profile_repo)
    #     repaired += 1
    return repaired
