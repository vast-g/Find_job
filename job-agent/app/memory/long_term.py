"""长期记忆：用户画像 + 跨会话摘要，存 user_profile 表。

写入前必须经过 memory.filter 过滤。
"""
from __future__ import annotations

import json

from app.db.repositories import ProfileRepository


class LongTermMemory:
    def __init__(self, repo: ProfileRepository):
        self.repo = repo

    async def get_profile(self, user_id: int) -> dict:
        p = await self.repo.get(user_id)
        if p is None:
            return {}
        return {
            "user_id": p.user_id,
            "resume_summary": p.resume_summary,
            "preferences": p.preferences or {},
            "goals": p.goals,
            "skills": p.skills or [],
            "cross_session_summary": p.cross_session_summary,
        }

    async def update_summary(self, user_id: int, summary: str) -> None:
        await self.repo.upsert_summary(user_id, summary)

    async def update_preferences(self, user_id: int, preferences: dict) -> None:
        p = await self.repo.get(user_id)
        if p is None:
            from app.db.models import UserProfile
            p = UserProfile(user_id=user_id)
        p.preferences = json.dumps(preferences, ensure_ascii=False)
        await self.repo.upsert_summary(user_id, p.cross_session_summary or "")
