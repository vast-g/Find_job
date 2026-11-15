"""Rerank：对混合检索结果精排，返回 Top5。

优先 CrossEncoder（sentence-transformers），未安装则降级为词重叠启发式。
输入/输出均为 langchain_core.documents.Document。
"""
from __future__ import annotations

from functools import lru_cache

from langchain_core.documents import Document

from app.config import get_settings


@lru_cache
def _cross_encoder():
    """仅当显式开启且能加载时才用 CrossEncoder（需联网下载模型）。"""
    if not get_settings().rerank_use_cross_encoder:
        return None
    try:
        from sentence_transformers import CrossEncoder
        return CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
    except Exception:
        return None


async def rerank(query: str, docs: list[Document], top_n: int = 5) -> list[Document]:
    if not docs:
        return []
    model = _cross_encoder()
    if model is not None:
        scores = model.predict([(query, d.page_content) for d in docs])
        for d, s in zip(docs, scores):
            d.metadata["score"] = float(s)
    else:
        q_tokens = set(_tokenize(query))
        for d in docs:
            d_tokens = _tokenize(d.page_content)
            if not d_tokens:
                d.metadata["score"] = 0.0
                continue
            inter = q_tokens & set(d_tokens)
            jaccard = len(inter) / len(q_tokens | set(d_tokens))
            coverage = len(inter) / len(q_tokens) if q_tokens else 0.0
            d.metadata["score"] = 0.6 * coverage + 0.4 * jaccard
    return sorted(docs, key=lambda d: -d.metadata.get("score", 0.0))[:top_n]


def _tokenize(text: str) -> list[str]:
    try:
        import jieba
        return [w for w in jieba.lcut(text) if w.strip()]
    except ImportError:
        return text.split()
