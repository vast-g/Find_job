"""验证新索引可用性：加载耗时 + 实际检索效果。

用法：
    python tools/verify_index.py
    python tools/verify_index.py "国企面试流程" "行测考什么"
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(errors="replace")
# 打开检索器的加载日志，便于看清"建 BM25"与"读缓存"的耗时差异
logging.basicConfig(level=logging.INFO, format="  [%(name)s] %(message)s")

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

QUERIES = sys.argv[1:] or [
    "国企面试从网申到签约一般有哪些环节？",
    "行测主要考什么内容？",
    "无领导小组讨论应该注意什么？",
]


async def main() -> int:
    from app.config import get_settings

    s = get_settings()
    print("=" * 70)
    print("索引可用性验证")
    print("=" * 70)
    print(f"  索引目录 : {s.faiss_index_dir}")
    print(f"  RAG_TOP_K: {s.rag_top_k}  (稠密/稀疏各取 {s.rag_top_k * 2}，RRF 保留 {s.rag_top_k})")
    print()

    # ── 1. 索引规模 ──
    import json

    docs_path = Path(s.faiss_index_dir) / "documents.jsonl"
    n_docs = sum(1 for line in docs_path.read_text(encoding="utf-8").splitlines() if line.strip())
    faiss_mb = (Path(s.faiss_index_dir) / "index.faiss").stat().st_size / 1024 / 1024
    print(f"  片段总数 : {n_docs}")
    print(f"  FAISS 大小: {faiss_mb:.1f} MB")

    # ── 2. 加载耗时 ──
    print()
    print("  加载中（首次检索会触发，之后常驻内存）...")
    from app.rag.hybrid_retriever import get_hybrid_retriever

    t0 = time.perf_counter()
    ret = get_hybrid_retriever()
    await ret.aget_relevant_documents("预热")
    load_s = time.perf_counter() - t0
    print(f"  >>> 加载耗时：{load_s:.1f} 秒")
    print(f"      （稠密={ret._dense is not None}, 稀疏 BM25={ret._sparse is not None}）")

    # ── 3. 检索 ──
    print()
    print("=" * 70)
    print("检索测试")
    print("=" * 70)
    for q in QUERIES:
        t0 = time.perf_counter()
        hits = await ret.aget_relevant_documents(q)
        dt = (time.perf_counter() - t0) * 1000
        print(f"\n  问题：{q}")
        print(f"  召回 {len(hits)} 条，耗时 {dt:.0f} ms")
        for i, d in enumerate(hits[:5], 1):
            did = d.metadata.get("doc_id", "?")
            txt = d.page_content.replace("\n", " ")[:64]
            print(f"    {i}. [{did}] {txt}...")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
