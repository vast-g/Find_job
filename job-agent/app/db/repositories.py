"""仓储层：消息 / 画像 / 轨迹的 CRUD。"""
from datetime import datetime

from sqlalchemy import delete, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Message, UserProfile, AgentTrace, SummaryFeedback

SHORT_TERM_TURNS = 10


class MessageRepository:
    def __init__(self, session: AsyncSession):
        self.s = session

    async def add(self, session_id: str, user_id: int, role: str, content: str, turn: int) -> Message:
        m = Message(session_id=session_id, user_id=user_id, role=role, content=content, turn=turn)
        self.s.add(m)
        await self.s.flush()
        return m

    async def recent(self, session_id: str, n: int = SHORT_TERM_TURNS) -> list[Message]:
        """短期记忆：当前会话最近 n 轮（一轮 = user + assistant）。"""
        stmt = (
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.turn.desc(), Message.id.desc())
            .limit(n * 2)
        )
        rows = (await self.s.execute(stmt)).scalars().all()
        return list(reversed(rows))

    async def count_turns(self, session_id: str) -> int:
        stmt = select(func.max(Message.turn)).where(Message.session_id == session_id)
        return (await self.s.execute(stmt)).scalar() or 0

    async def delete_by_session(self, session_id: str) -> None:
        await self.s.execute(delete(Message).where(Message.session_id == session_id))


class ProfileRepository:
    def __init__(self, session: AsyncSession):
        self.s = session

    async def get(self, user_id: int) -> UserProfile | None:
        stmt = select(UserProfile).where(UserProfile.user_id == user_id)
        return (await self.s.execute(stmt)).scalar_one_or_none()

    async def upsert_summary(self, user_id: int, summary: str) -> None:
        p = await self.get(user_id)
        if p is None:
            p = UserProfile(user_id=user_id)
            self.s.add(p)
        p.cross_session_summary = summary
        await self.s.flush()

    async def upsert_profile(
        self,
        user_id: int,
        *,
        summary: str | None = None,
        goals: str | None = None,
        preferences: dict | None = None,
        skills: list | None = None,
        resume_summary: str | None = None,
    ) -> None:
        p = await self.get(user_id)
        if p is None:
            p = UserProfile(user_id=user_id)
            self.s.add(p)
        if summary is not None:
            p.cross_session_summary = summary
            p.summary_updated_at = datetime.now()
        if goals is not None:
            p.goals = goals
        if resume_summary is not None:
            p.resume_summary = resume_summary
        if preferences is not None:
            merged = dict(p.preferences or {})
            merged.update(preferences)
            p.preferences = merged
        if skills is not None:
            merged = list(p.skills or [])
            for s in skills:
                if s and s not in merged:
                    merged.append(s)
            p.skills = merged
        await self.s.flush()


class TraceRepository:
    def __init__(self, session: AsyncSession):
        self.s = session

    async def add(self, trace: AgentTrace) -> None:
        self.s.add(trace)
        await self.s.flush()


class FeedbackRepository:
    def __init__(self, session: AsyncSession):
        self.s = session

    async def add(self, user_id: int, summary_text: str | None, rating: int, correction: str | None) -> None:
        self.s.add(SummaryFeedback(
            user_id=user_id, summary_text=summary_text, rating=rating, correction=correction
        ))
        await self.s.flush()
