"""混合检索：FAISS（稠密）+ BM25（稀疏），RRF 融合。

## 修复记录：BM25 对中文原本完全失效

原来的写法是 `BM25Retriever.from_documents(docs, k=...)`，用的是 langchain 的
默认预处理 `text.split()` —— **按空格切**。中文没有空格，于是每个 400 字片段
被切成 1 个 token，查询同理，BM25 只有"字面完全相同"才可能命中。

结果是：号称"稠密 + 稀疏混合检索"，实际**稀疏那一路完全没工作**，
召回能力白白浪费（这也解释了为什么有些最相关的文档没被召回）。

修复：传入 jieba 分词器（`app/rag/tokenizer.py`）。

## 附带解决：启动变慢的问题

jieba 给 1.4 万个片段分词要几十秒，直接做会让首次检索从 2.4 秒变成 30-60 秒。
因此加了 **BM25 索引磁盘缓存**：第一次构建后 pickle 到 `bm25_cache.pkl`，
之后启动直接反序列化（约 1-2 秒）。缓存以 documents.jsonl 的
「大小 + 修改时间」为指纹，索引一重建缓存自动失效。
"""
from __future__ import annotations

import json
import logging
import os
import pickle
import time

from langchain_core.documents import Document

from app.config import get_settings
from app.rag.tokenizer import tokenize_zh

log = logging.getLogger("app.rag.retriever")

BM25_CACHE_FILE = "bm25_cache.pkl"


class HybridRetriever:
    def __init__(self, top_k: int | None = None):
        self.top_k = top_k or get_settings().rag_top_k
        self._dense = None
        self._sparse = None

    # ---------- 加载 ----------
    def _ensure_loaded(self) -> None:
        if self._dense is not None or self._sparse is not None:
            return
        from langchain_community.vectorstores import FAISS

        from app.rag.embeddings import get_embedder

        path = get_settings().faiss_index_dir
        t0 = time.perf_counter()

        if os.path.exists(os.path.join(path, "index.faiss")):
            vs = FAISS.load_local(path, get_embedder(), allow_dangerous_deserialization=True)
            self._dense = vs.as_retriever(search_kwargs={"k": self.top_k * 2})
            log.info("稠密索引加载完成 %.1fs", time.perf_counter() - t0)

        docs_file = os.path.join(path, "documents.jsonl")
        if os.path.exists(docs_file):
            docs = self._read_docs(docs_file)
            if docs:
                t1 = time.perf_counter()
                self._sparse = self._load_bm25(path, docs_file, docs)
                log.info("BM25 就绪 %.1fs（%d 篇）", time.perf_counter() - t1, len(docs))

    @staticmethod
    def _read_docs(docs_file: str) -> list[Document]:
        docs: list[Document] = []
        with open(docs_file, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    d = json.loads(line)
                    docs.append(Document(page_content=d["content"], metadata=d.get("metadata", {})))
        return docs

    # ---------- BM25：优先读缓存，未命中则构建并落盘 ----------
    def _load_bm25(self, path: str, docs_file: str, docs: list[Document]):
        from langchain_community.retrievers import BM25Retriever

        k = self.top_k * 2
        # 缓存指纹：中文分词 + documents.jsonl 的大小与修改时间
        # 索引一重建，指纹就变，旧缓存自动失效，避免用到不匹配的 BM25。
        try:
            st = os.stat(docs_file)
            stamp = f"{st.st_size}:{int(st.st_mtime)}:{k}"
        except OSError:
            stamp = ""

        cache_path = os.path.join(path, BM25_CACHE_FILE)
        if stamp and os.path.exists(cache_path):
            try:
                with open(cache_path, "rb") as f:
                    payload = pickle.load(f)
                if payload.get("stamp") == stamp:
                    log.info("BM25 命中磁盘缓存")
                    return payload["retriever"]
                log.info("BM25 缓存已过期（语料变更），重新构建")
            except Exception as exc:  # noqa: BLE001
                log.warning("BM25 缓存不可用（%s: %s），重新构建", type(exc).__name__, exc)

        use_zh = get_settings().bm25_chinese_tokenizer
        t0 = time.perf_counter()
        if use_zh:
            # 注意字段名是 `preprocess_func`（不是 `preprocessor`）。
            # langchain 各版本命名不一致，传错名字会被 pydantic 当额外字段**静默忽略**：
            # 不报错、不警告，但分词器根本没换 —— 实测踩过这个坑（构建只用 0.2s，
            # 而正确分词需要约 10s，且 retriever.preprocess_func 仍是默认函数）。
            retriever = BM25Retriever.from_documents(docs, k=k, preprocess_func=tokenize_zh)
        else:
            retriever = BM25Retriever.from_documents(docs, k=k)
        log.info("BM25 构建完成 %.1fs（中文分词=%s）", time.perf_counter() - t0, use_zh)

        # 防御性校验：确认分词器真的换上了，避免"以为修好其实没生效"
        if use_zh and getattr(retriever, "preprocess_func", None) is not tokenize_zh:
            raise RuntimeError(
                "BM25 中文分词未生效：当前 langchain 版本的字段名与 preprocess_func 不符，"
                f"实际取到 {getattr(retriever, 'preprocess_func', None)!r}。"
                "请检查 langchain_community.retrievers.BM25Retriever 的字段定义。"
            )

        if stamp:
            try:
                with open(cache_path, "wb") as f:
                    pickle.dump({"stamp": stamp, "k": k, "retriever": retriever}, f)
            except Exception as exc:  # noqa: BLE001
                log.warning("BM25 缓存写入失败（不影响本次运行）：%s", exc)
        return retriever

    # ---------- 检索 ----------
    async def aget_relevant_documents(self, query: str) -> list[Document]:
        self._ensure_loaded()
        dense, sparse = [], []
        if self._dense is not None:
            # langchain-core 1.x：BaseRetriever 异步接口是 ainvoke
            dense = await self._dense.ainvoke(query)
        if self._sparse is not None:
            sparse = self._sparse.invoke(query)
        return self._rrf_fusion(dense, sparse)

    def _rrf_fusion(self, dense: list[Document], sparse: list[Document], rrf_k: int = 60) -> list[Document]:
        score_map: dict[str, float] = {}
        doc_map: dict[str, Document] = {}
        for rank, d in enumerate(dense):
            key = d.page_content
            score_map[key] = score_map.get(key, 0.0) + 1.0 / (rrf_k + rank + 1)
            doc_map[key] = d
        for rank, d in enumerate(sparse):
            key = d.page_content
            score_map[key] = score_map.get(key, 0.0) + 1.0 / (rrf_k + rank + 1)
            doc_map.setdefault(key, d)
        ranked = sorted(score_map.items(), key=lambda x: -x[1])[: self.top_k]
        out = []
        for key, score in ranked:
            d = doc_map[key]
            d.metadata["score"] = score
            out.append(d)
        return out


_retriever: HybridRetriever | None = None


def get_hybrid_retriever() -> HybridRetriever:
    global _retriever
    if _retriever is None:
        _retriever = HybridRetriever()
    return _retriever


def reset_retriever() -> None:
    """清空单例（测试或切换索引后使用）。"""
    global _retriever
    _retriever = None
