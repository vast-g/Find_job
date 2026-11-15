"""题库诊断 + doc_id 目录导出。

用途：
  1. 看清 testset.jsonl 的字段结构与分布（扩题前必看）
  2. 导出索引中真实存在的 doc_id 目录，供新题标注 ground_truth_docs
     （标注了不存在的 doc_id 会让 Recall@K 恒为 0 —— 这个坑踩过一次）

用法：
    python tools/dataset_report.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "benchmark" / "reports" / "dataset_report.txt"
OUT.parent.mkdir(parents=True, exist_ok=True)
_fh = OUT.open("w", encoding="utf-8")


class Tee:
    def write(self, s):
        _fh.write(s)
        try:
            sys.__stdout__.write(s)
        except Exception:  # noqa: BLE001
            pass

    def flush(self):
        _fh.flush()
        try:
            sys.__stdout__.flush()
        except Exception:  # noqa: BLE001
            pass


sys.stdout = Tee()
sys.stderr = Tee()

DATASET = BASE / "benchmark" / "dataset" / "testset.jsonl"
INDEX_DOCS = BASE / "data" / "faiss" / "documents.jsonl"
KNOWLEDGE = BASE / "data" / "knowledge.jsonl"
OUT_DOCIDS = BASE / "benchmark" / "dataset" / "doc_id_catalog.txt"


def load_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").split("\n") if line.strip()]


def main() -> int:
    cases = load_jsonl(DATASET)

    print("=" * 84)
    print("1) 题库字段结构（第 1 条完整样例）")
    print("=" * 84)
    if cases:
        print(json.dumps(cases[0], ensure_ascii=False, indent=2))
        print()
        print("  全部字段:", list(cases[0].keys()))

    print()
    print("=" * 84)
    print(f"2) 字段分布（共 {len(cases)} 条）")
    print("=" * 84)
    for k in ("category", "expected_intent", "difficulty", "adversarial", "reviewed"):
        c = Counter(str(x.get(k)) for x in cases)
        print(f"  {k:<18}: {dict(c)}")

    expected_fields = Counter()
    for x in cases:
        for f in (x.get("expected") or {}):
            expected_fields[f] += 1
    print(f"  expected 子字段     : {dict(expected_fields)}")
    print(f"  有 success_criteria : {sum(1 for x in cases if x.get('success_criteria'))}")
    print(f"  有 setup（多轮）    : {sum(1 for x in cases if x.get('setup'))}")
    print(f"  有 expected_tools   : {sum(1 for x in cases if x.get('expected_tools'))}")

    withgt = [x for x in cases if x.get("ground_truth_docs")]
    print(f"  带 ground_truth_docs: {len(withgt)}/{len(cases)}"
          f"  ({len(withgt) * 100 // max(1, len(cases))}%)  <-- 只有这些参与 Recall@K")
    for x in withgt[:5]:
        print(f"    #{x.get('id')} {x.get('ground_truth_docs')}")

    # ── doc_id 目录 ──
    print()
    print("=" * 84)
    print("3) 索引中真实存在的 doc_id（新题标注必须从这里取）")
    print("=" * 84)
    doc_ids: list[str] = []
    if KNOWLEDGE.exists():
        doc_ids += [json.loads(l)["doc_id"] for l in
                    KNOWLEDGE.read_text(encoding="utf-8").split("\n") if l.strip()]
    external: dict[str, int] = defaultdict(int)
    if INDEX_DOCS.exists():
        for line in INDEX_DOCS.read_text(encoding="utf-8").split("\n"):
            line = line.strip()
            if not line:
                continue
            did = json.loads(line)["metadata"].get("doc_id", "")
            src = did.split("#")[0]
            if src and not src.startswith("doc_"):
                external[src] += 1

    print(f"  知识库精炼条目 doc_id: {len(doc_ids)} 个")
    for d in doc_ids:
        print(f"    {d}")
    print()
    print(f"  外部资料源文档: {len(external)} 篇（片段数 top 30）")
    for src, n in sorted(external.items(), key=lambda x: -x[1])[:30]:
        print(f"    [{n:>4} 片段] {src}")

    # 按顶层目录分组，便于按板块出题
    groups: dict[str, list[str]] = defaultdict(list)
    for src in external:
        top = src.split("\\")[0].split("/")[0]
        groups[top].append(src)
    print()
    print("  按板块分组:")
    for top in sorted(groups, key=lambda t: -len(groups[t])):
        print(f"    {top:<28} {len(groups[top])} 篇")

    # 写出完整目录供生成时引用
    lines = ["# 可用 doc_id 目录（新题 ground_truth_docs 必须取自这里）", "", "## 知识库精炼条目"]
    lines += doc_ids
    lines += ["", "## 外部资料来源文档（相对路径，不含扩展名）"]
    lines += sorted(external)
    OUT_DOCIDS.write_text("\n".join(lines), encoding="utf-8")
    print()
    print(f"  完整目录已写出: {OUT_DOCIDS}（{len(doc_ids) + len(external)} 条）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
