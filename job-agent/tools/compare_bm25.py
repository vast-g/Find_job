"""A/B 对比：BM25 用中文分词 vs 用 langchain 默认（按空格切）。

目的：用数据说明"BM25 中文分词失效"到底损失了多少召回能力。

    python tools/_ab_bm25.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(errors="replace")
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from langchain_community.retrievers import BM25Retriever  # noqa: E402
from langchain_community.retrievers.bm25 import default_preprocessing_func  # noqa: E402
from langchain_core.documents import Document  # noqa: E402

from app.rag.tokenizer import tokenize_zh  # noqa: E402

# ── 1. 确认线上检索器用的分词器 ──
print("=" * 70)
print("1) 线上检索器的实际分词器")
print("=" * 70)
from app.rag.hybrid_retriever import get_hybrid_retriever  # noqa: E402

r = get_hybrid_retriever()
r._ensure_loaded()
pf = getattr(r._sparse, "preprocess_func", None)
print(f"  preprocess_func = {pf}")
print(f"  是中文分词器?   = {pf is tokenize_zh}")

# ── 2. 准备样本语料 ──
print()
print("=" * 70)
print("2) A/B 对比（取前 4000 个片段做样本，控制耗时）")
print("=" * 70)
docs: list[Document] = []
with (BASE / "data" / "faiss" / "documents.jsonl").open(encoding="utf-8") as f:
    for line in f:
        if not line.strip():
            continue
        d = json.loads(line)
        docs.append(Document(page_content=d["content"], metadata=d.get("metadata", {})))
        if len(docs) >= 4000:
            break

t0 = time.perf_counter()
bm_default = BM25Retriever.from_documents(docs, k=10)
t_default = time.perf_counter() - t0

t0 = time.perf_counter()
bm_zh = BM25Retriever.from_documents(docs, k=10, preprocess_func=tokenize_zh)
t_zh = time.perf_counter() - t0

print(f"  样本 {len(docs)} 篇")
print(f"  默认分词构建耗时 : {t_default:.2f}s")
print(f"  中文分词构建耗时 : {t_zh:.2f}s")

# ── 3. 逐查询对比 ──
QUERIES = [
    "国企面试从网申到签约一般有哪些环节？",
    "无领导小组讨论应该注意什么？",
    "行测和申论分别考什么？",
    "谈薪的时候要注意什么？",
]
print()
for q in QUERIES:
    a = bm_default.invoke(q)
    b = bm_zh.invoke(q)
    da = {d.metadata.get("doc_id", "") for d in a}
    db = {d.metadata.get("doc_id", "") for d in b}
    print(f"  问题：{q}")
    print(f"    默认分词 top10: {sorted(da)[:4]}")
    print(f"    中文分词 top10: {sorted(db)[:4]}")
    print(f"    仅中文分词召回到的: {sorted(db - da)[:4] or '（无差异）'}")
    print()
