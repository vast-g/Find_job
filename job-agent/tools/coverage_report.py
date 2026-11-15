"""评测集覆盖率诊断：找出"有资料但没题"的空白区，指导扩充。

用法：
    python tools/coverage_report.py

为什么需要：语料从 18 片段扩到 1.4 万片段后，新资料里绝大多数没有被任何
测试题覆盖。此时"把题量从 75 加到 200"如果只是重复已有类别，指标不会更可信。
**覆盖率**比题量更能决定评测的说服力。
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(errors="replace")

BASE = Path(__file__).resolve().parent.parent
DATASET = BASE / "benchmark" / "dataset" / "testset.jsonl"
EXTRA = BASE / "benchmark" / "dataset" / "testset_extra.jsonl"
INDEX = BASE / "data" / "faiss" / "documents.jsonl"
KNOWLEDGE = BASE / "data" / "knowledge.jsonl"

CATEGORIES = ["岗位推荐", "简历优化", "面试问答", "对抗性"]


def load_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").split("\n"):
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def main() -> int:
    cases = load_jsonl(DATASET) + load_jsonl(EXTRA)
    if not cases:
        print("评测集为空")
        return 1

    print("=" * 72)
    print("评测集覆盖率诊断")
    print("=" * 72)
    print(f"  题量: {len(cases)} 条")
    print()

    # ── 1. 分布 ──
    print("  类别分布：")
    cc = Counter(c.get("category", "?") for c in cases)
    for cat in CATEGORIES:
        print(f"    {cat:8s} {cc.get(cat, 0):3d}")
    for k, v in cc.items():
        if k not in CATEGORIES:
            print(f"    {k} (未知类别) {v}")

    print()
    print("  意图分布：")
    for k, v in sorted(Counter(c.get("expected_intent", "?") for c in cases).items()):
        print(f"    {k:12s} {v:3d}")

    print()
    print("  难度分布：")
    for k, v in sorted(Counter(c.get("difficulty", 0) for c in cases).items()):
        print(f"    难度 {k}  {v:3d}")

    adv = sum(1 for c in cases if c.get("adversarial"))
    multi = sum(1 for c in cases if c.get("setup"))
    print(f"  对抗样本: {adv}    多轮(setup)样本: {multi}   <-- 多轮覆盖几乎为零")

    # ── 2. 检索标注覆盖 ──
    labeled = [c for c in cases if c.get("ground_truth_docs")]
    print()
    print("=" * 72)
    print("检索标注覆盖（决定 Recall@K 是否可信）")
    print("=" * 72)
    print(f"  有 ground_truth_docs 的题: {len(labeled)} / {len(cases)}"
          f"  ({len(labeled) * 100 // max(1, len(cases))}%)")
    print("  → **只有这些题参与 Recall@K 计算**。比例太低则检索指标代表性不足。")

    used_docs = {d for c in labeled for d in (c.get("ground_truth_docs") or [])}

    # ── 3. 索引内文档 vs 被引用的文档 ──
    if INDEX.exists():
        all_docs = Counter()
        for line in INDEX.read_text(encoding="utf-8").split("\n"):
            line = line.strip()
            if not line:
                continue
            did = json.loads(line)["metadata"].get("doc_id", "")
            all_docs[did.split("#")[0]] += 1

        print()
        print(f"  索引内来源文档: {len(all_docs)} 篇")
        print(f"  被题目引用    : {len(used_docs)} 篇")
        uncovered = sorted(set(all_docs) - used_docs)
        print(f"  **无题覆盖**  : {len(uncovered)} 篇"
              f"  ({(len(uncovered) * 100) // max(1, len(all_docs))}%)")

        # 按顶层目录归类，看哪些板块完全没题
        groups: dict[str, list[str]] = defaultdict(list)
        for d in all_docs:
            top = d.split("\\")[0].split("/")[0]
            groups[top].append(d)

        print()
        print("  按板块看覆盖情况：")
        print(f"    {'板块':<34} {'总篇数':>6} {'已覆盖':>6} {'空白':>6}")
        print("    " + "-" * 60)
        for top in sorted(groups, key=lambda t: -len(groups[t])):
            total = groups[top]
            hit = sum(1 for d in total if d in used_docs)
            gap = len(total) - hit
            mark = "  <-- 全空白" if hit == 0 and len(total) > 3 else ""
            print(f"    {top[:34]:<34} {len(total):>6} {hit:>6} {gap:>6}{mark}")

        print()
        print("  空白最多的 15 篇（建议优先为它们出题）：")
        for d in uncovered[:15]:
            print(f"    - {d[:80]}")

    print()
    print("=" * 72)
    print("扩充建议")
    print("=" * 72)
    print("  1. 优先补「有资料但无题」的板块 —— 尤其是行测/申论/公基/时政/真题")
    print("  2. 提高检索标注比例：目标让 40%+ 的题带 ground_truth_docs")
    print("     （只有带标注的题才参与 Recall@K）")
    print("  3. 补多轮样本（用 setup 字段）—— 目前几乎为零，记忆能力没有覆盖")
    print("  4. 保持四类配比：面试问答最多（知识密集），对抗性保持 15-20%")
    print()
    print("  ⚠️ 扩充后指标会整体位移，**不要和扩充前的报告直接比较**。")
    print("     正确做法：扩充完成后重跑一次作为新基线。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
