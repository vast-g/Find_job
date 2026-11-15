"""工具：search_knowledge —— RAG 检索求职知识库。"""
from __future__ import annotations

from langchain_core.tools import tool

from app.rag.hybrid_retriever import get_hybrid_retriever
from app.rag.query_rewrite import rewrite_query
from app.rag.rerank import rerank
from app.tools.registry import register_tool


@tool
async def search_knowledge(query: str) -> list[dict]:
    """检索求职知识库（面试技巧/行业知识/流程答疑）。输入自然语言问题。"""
    ret = get_hybrid_retriever()
    queries = await rewrite_query(query)
    docs = []
    seen: set[str] = set()
    for q in queries:
        for d in await ret.aget_relevant_documents(q):
            if d.page_content and d.page_content not in seen:
                seen.add(d.page_content)
                docs.append(d)
    top = await rerank(query, docs)
    return [{"doc_id": d.metadata.get("doc_id", ""), "content": d.page_content, "score": d.metadata.get("score", 0.0), "source": d.metadata.get("source", "")} for d in top]


register_tool(search_knowledge)
