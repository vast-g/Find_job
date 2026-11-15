"""列出知识库索引中的全部 doc_id，并给出可用格式说明。

新增资料后用它确认"资料是否真的进了索引"，以及拿到 doc_id
（标注评测集的 ground_truth_docs 时需要用到）。

用法：
    python tools/list_docs.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(errors="replace")

INDEX = BASE / "data" / "faiss" / "documents.jsonl"
KNOWLEDGE = BASE / "data" / "knowledge.jsonl"
DOCS_DIR = BASE / "data" / "docs"

SUPPORTED = {".txt", ".md", ".docx", ".pdf"}


def main() -> int:
    print("=" * 70)
    print("知识库索引 doc_id 清单")
    print("=" * 70)

    if not INDEX.exists():
        print(f"索引不存在：{INDEX}")
        print("请先运行： python -m app.rag.indexer build_all")
        return 1

    rows = []
    for line in INDEX.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))

    base = Counter((r.get("metadata", {}).get("doc_id") or "").split("#")[0] for r in rows)

    print(f"索引位置 : {INDEX}")
    print(f"片段总数 : {len(rows)}")
    print(f"来源文档 : {len(base)} 篇")
    print()
    print(f"{'doc_id':<40} {'片段数':>6}  来源")
    print("-" * 70)
    for doc_id, n in sorted(base.items()):
        src = ""
        for r in rows:
            if (r.get("metadata", {}).get("doc_id") or "").split("#")[0] == doc_id:
                src = r.get("metadata", {}).get("source", "")
                break
        print(f"{doc_id:<40} {n:>6}  {src}")

    print()
    print("=" * 70)
    print("如何新增资料")
    print("=" * 70)
    n_kb = 0
    if KNOWLEDGE.exists():
        n_kb = len([l for l in KNOWLEDGE.read_text(encoding="utf-8").splitlines() if l.strip()])
    print(f"1) 短条目 / 问答式知识 → 追加到 {KNOWLEDGE.relative_to(BASE)}")
    print(f"   （当前 {n_kb} 条；每行一个 JSON：{{\"doc_id\":..., \"source\":..., \"content\":...}}）")
    print(f"2) 长文档 / 表格 / 制度文件 → 放进 {DOCS_DIR.relative_to(BASE)}\\")
    files = sorted(p.name for p in DOCS_DIR.iterdir()
                   if p.is_file() and p.suffix.lower() in SUPPORTED) if DOCS_DIR.exists() else []
    print(f"   （当前 {len(files)} 个：{', '.join(files) if files else '无'}）")
    print(f"   支持格式：{', '.join(sorted(SUPPORTED))}")
    print()
    print("放好后运行： python -m app.rag.indexer build_all")
    print("（或直接双击项目根目录的「重建知识库.bat」）")
    print()
    print("⚠️ 索引重建后，评测集里引用旧结构的 ground_truth_docs 可能需要同步更新；")
    print("   新增资料对应的新问题也要补进 benchmark/dataset/testset.jsonl，")
    print("   否则新知识的检索质量（Recall@K）测不出来。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
