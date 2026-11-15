"""记忆接口：反馈 / 手动修正。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import MemoryCorrectRequest, MemoryFeedbackRequest
from app.db.repositories import FeedbackRepository, ProfileRepository
from app.db.session import get_db
from app.memory.repair import manual_correct, record_feedback

router = APIRouter(prefix="/memory", tags=["memory"])


@router.post("/feedback")
async def feedback(req: MemoryFeedbackRequest, session: AsyncSession = Depends(get_db)):
    await record_feedback(req.user_id, req.summary_text, req.rating, req.correction, FeedbackRepository(session))
    await session.commit()
    return {"ok": True}


@router.post("/correct")
async def correct(req: MemoryCorrectRequest, session: AsyncSession = Depends(get_db)):
    await manual_correct(req.user_id, req.new_summary, ProfileRepository(session))
    await session.commit()
    return {"ok": True}
