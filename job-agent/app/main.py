"""FastAPI 入口。启动：python -m app.main"""
from __future__ import annotations

from fastapi import FastAPI

from app.api.routes import agent, benchmark, memory

app = FastAPI(title="求职系统 AI Agent", version="1.0")

app.include_router(agent.router)
app.include_router(memory.router)
app.include_router(benchmark.router)


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
