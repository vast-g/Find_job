"""Agent 核心接口：chat / recommend。

与现有后端 job-platform 约定的接口保持一致（/agent/chat 等）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from redis.exceptions import RedisError
from app.memory.errors import SessionBusyError, SessionLeaseLostError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import AnalyzeRequest, AnswerFeedbackRequest, ChatRequest, ChatResponse, RecommendRequest
from app.core.pipeline import AgentPipeline
from app.db.session import get_db

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, session: AsyncSession = Depends(get_db)):
    pipeline = AgentPipeline(session)
    try:
        result = await pipeline.handle(req.user_id, req.message, req.session_id)
    except SessionBusyError:
        raise HTTPException(status_code=409, detail="上一条回复正在生成，请稍后再发送") from None
    except SessionLeaseLostError:
        raise HTTPException(status_code=503, detail="会话状态暂时不可用，请稍后重试") from None
    except TimeoutError:
        raise HTTPException(status_code=504, detail="本次回复超时，请稍后重试") from None
    except RedisError:
        raise HTTPException(status_code=503, detail="会话记忆暂时不可用，请稍后重试") from None
    return ChatResponse(**result)


@router.post("/recommend")
async def recommend(req: RecommendRequest, session: AsyncSession = Depends(get_db)):
    """岗位推荐：直接走推荐子 Agent，返回岗位列表。"""
    from app.agents.sub_agents import RecommenderAgent
    from app.tools.resume_tools import get_user_resume
    from app.core.context import reset_current_user, set_current_user
    token = set_current_user(req.user_id)
    try:
        resume = await get_user_resume.ainvoke({})
        result = await RecommenderAgent().run({}, resume=resume)
        return {"user_id": req.user_id, "answer": result["answer"]}
    finally:
        reset_current_user(token)


@router.post("/analyze")
async def analyze(req: AnalyzeRequest):
    """岗位分析：结合用户简历与岗位 JD，输出五部分综合分析。"""
    from app.agents.sub_agents import JobMatchAnalyzerAgent
    result = await JobMatchAnalyzerAgent().run({}, job=req.job, resume=req.resume or {})
    return {"answer": result["answer"]}


@router.post("/feedback")
async def feedback(req: AnswerFeedbackRequest, session: AsyncSession = Depends(get_db)):
    """用户对某次回答的反馈，写入 agent_trace（node=feedback）。"""
    from app.db.models import AgentTrace
    from app.db.repositories import TraceRepository
    await TraceRepository(session).add(AgentTrace(
        request_id=req.request_id or req.session_id,
        session_id=req.session_id,
        user_id=req.user_id,
        step=0,
        node="feedback",
        input=str(req.rating),
        output=req.comment,
    ))
    await session.commit()
    return {"ok": True}
