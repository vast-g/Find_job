"""Benchmark 触发接口。"""
from __future__ import annotations

from fastapi import APIRouter

from app.api.schemas import BenchmarkRequest

router = APIRouter(prefix="/benchmark", tags=["benchmark"])


@router.post("/run")
async def run_benchmark(req: BenchmarkRequest):
    """异步触发评测，返回报告路径。生产建议走后台任务/队列。"""
    from benchmark.evaluate import run_evaluation
    report = await run_evaluation(req.dataset_path, req.run_tag, req.limit)
    return {"run_tag": req.run_tag, "report": report}
