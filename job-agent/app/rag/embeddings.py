"""Embedding 抽象：返回 LangChain Embeddings 对象。

支持 Ollama（langchain-ollama）或本地 sentence-transformers。
"""
from __future__ import annotations

from functools import lru_cache

from langchain_core.embeddings import Embeddings

from app.config import get_settings


class LocalHFEmbeddings(Embeddings):
    """本地 sentence-transformers 封装为 LangChain Embeddings。"""

    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer
        self._m = SentenceTransformer(model_name)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._m.encode(texts, normalize_embeddings=True)]

    def embed_query(self, text: str) -> list[float]:
        return self._m.encode([text], normalize_embeddings=True)[0].tolist()


@lru_cache
def get_embedder() -> Embeddings:
    s = get_settings()
    if s.embedding_provider == "sentence-transformers":
        return LocalHFEmbeddings(s.embedding_model)
    from langchain_ollama import OllamaEmbeddings

    # keep_alive：构建大索引要连续跑十几分钟。若模型中途被 Ollama 卸载再重载，
    # 会分配新的内部端口（llama-server），持有旧端口引用的客户端会连不上
    # （实测报 "actively refused"）。让模型常驻可从根上避免这类中断。
    return OllamaEmbeddings(
        model=s.embedding_model,
        base_url=s.ollama_base_url,
        keep_alive=s.embedding_keep_alive,
    )
