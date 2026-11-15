"""Pydantic 请求/响应模型。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    user_id: int
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    source: str = "react"
    intent: str | None = None
    request_id: str | None = None
    latency_ms: int | None = None
    stats: dict[str, Any] | None = None


class RecommendRequest(BaseModel):
    user_id: int
    top_n: int = 10


class AnalyzeRequest(BaseModel):
    user_id: int
    job: dict
    resume: dict | None = None


class AnswerFeedbackRequest(BaseModel):
    request_id: str | None = None
    session_id: str
    user_id: int
    rating: int = Field(..., ge=0, le=1, description="1 赞 / 0 踩")
    comment: str | None = None


class MemoryFeedbackRequest(BaseModel):
    user_id: int
    summary_text: str | None = None
    rating: int = Field(..., ge=0, le=1, description="1 有效 / 0 无效")
    correction: str | None = None


class MemoryCorrectRequest(BaseModel):
    user_id: int
    new_summary: str


class BenchmarkRequest(BaseModel):
    run_tag: str
    dataset_path: str | None = None
    limit: int | None = None
