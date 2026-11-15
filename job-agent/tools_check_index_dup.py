"""检查求职平台 RAG 索引是不是有大量重复块。

背景：源语料只有 knowledge.jsonl(7.6KB) + 一个 docx(36KB) + 一个 txt，
但 faiss/documents.jsonl 有 14059 行、810 万字符、平均每块 578 字符 ——
体量对不上。要看是不是**同一个索引被反复追加**导致的重复。
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(errors="replace")

F = Path(r"C:\Users\Lenovo\Desktop\Find_job\job-agent\data\faiss\documents.jsonl")

texts: list[str] = []
meta: list[str] = []
with F.open(encoding="utf-8") as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue
        # 这个项目的持久化格式是 {"content": ..., "metadata": {...}}
        # （不是 LangChain 默认的 page_content，所以第一版解析器一条都没匹配上）
        body = o.get("content", o.get("page_content"))
        if body is None:
            for v in o.values():
                if isinstance(v, dict):
                    body = v.get("content", v.get("page_content"))
                    if body is not None:
                        o = v
                        break
        if body is None:
            continue
        texts.append(str(body))
        meta.append(str((o.get("metadata") or {}).get("doc_id", "")))

print("=" * 70)
print("求职平台 RAG 索引重复度检查")
print("=" * 70)
print(f"  解析出块数      : {len(texts)}")
print(f"  总字符数        : {sum(len(t) for t in texts):,}")
print(f"  平均每块字符    : {sum(len(t) for t in texts) / max(1, len(texts)):.0f}")

# 完全相同的块
h = [hashlib.md5(t.encode("utf-8")).hexdigest() for t in texts]
uniq = len(set(h))
print()
print(f"  去重后唯一块数  : {uniq}")
print(f"  重复率          : {(1 - uniq / max(1, len(texts))) * 100:.1f}%")

# 出现最多的内容
print()
print("  出现次数最多的 5 个块：")
for content, n in Counter(texts).most_common(5):
    print(f"    ×{n:<6} {content[:70]!r}")

# 来源分布
print()
print("  来源文件分布（前 8）：")
for src, n in Counter(meta).most_common(8):
    print(f"    {n:<7} {src}")

# 分段长度分布
print()
lens = sorted(len(t) for t in texts)
if lens:
    print(f"  块长度 最小/中位/最大: {lens[0]} / {lens[len(lens)//2]} / {lens[-1]}")
