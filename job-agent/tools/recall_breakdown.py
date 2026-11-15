"""拆解 Recall@K：区分「精炼知识条目」与「外部资料文档」两类标注。

背景：题库从 75 题扩到 200 题后，带检索标注的用例由 24 条增至 111 条，
其中绝大多数指向**外部资料**（笔试/真题/面试资料，共 432 篇），
而原来的 24 条主要指向 16 条**精炼知识条目**（doc_* 前缀，内容短且高度对口）。

这两类的检索难度差异极大，混在一起看会误判为"检索质量下降"。
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "benchmark" / "reports" / "recall_breakdown.txt"
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


sys.stdout = Tee()

REPORTS = BASE / "benchmark" / "reports"
res = sorted(REPORTS.glob("eval_results_*.json"), key=lambda p: p.stat().st_mtime)[-1]
d = json.loads(res.read_text(encoding="utf-8"))
samples = d.get("samples") or []
print(f"结果文件: {res.name}  样本 {len(samples)}")

labeled = [s for s in samples if s.get("ground_truth_docs")]
print(f"带检索标注: {len(labeled)}")


def kind(s: dict) -> str:
    docs = s["ground_truth_docs"]
    all_curated = all(str(x).startswith("doc_") for x in docs)
    all_ext = all(not str(x).startswith("doc_") for x in docs)
    if all_curated:
        return "精炼知识条目(doc_*)"
    if all_ext:
        return "外部资料文档"
    return "混合"


groups: dict[str, list] = defaultdict(list)
for s in labeled:
    groups[kind(s)].append(s)

print()
print("=" * 80)
print("Recall@K 分类拆解")
print("=" * 80)
print(f"  {'类别':<22} {'样本':>5} {'Recall@K':>10} {'Hit@K':>9}")
print("  " + "-" * 52)
for g, items in sorted(groups.items(), key=lambda x: -len(x[1])):
    rr = [s.get("recall_at_k") or 0 for s in items]
    hk = [1.0 if (s.get("hit_at_k") or 0) else 0.0 for s in items]
    print(f"  {g:<22} {len(items):>5} {sum(rr)/len(rr)*100:>9.1f}% {sum(hk)/len(hk)*100:>8.1f}%")

allrr = [s.get("recall_at_k") or 0 for s in labeled]
allhk = [1.0 if (s.get("hit_at_k") or 0) else 0.0 for s in labeled]
print("  " + "-" * 52)
print(f"  {'合计':<22} {len(labeled):>5} {sum(allrr)/len(allrr)*100:>9.1f}% {sum(allhk)/len(allhk)*100:>8.1f}%")

print()
print("=" * 80)
print("按类别看 Recall@K")
print("=" * 80)
bycat: dict[str, list] = defaultdict(list)
for s in labeled:
    bycat[s.get("category")].append(s)
for c, items in sorted(bycat.items(), key=lambda x: -len(x[1])):
    rr = [s.get("recall_at_k") or 0 for s in items]
    print(f"  {c:<10} 样本 {len(items):>3}  Recall@K {sum(rr)/len(rr)*100:>5.1f}%")

print()
print("=" * 80)
print("未命中的用例（Recall@K = 0）样例")
print("=" * 80)
zero = [s for s in labeled if not (s.get("recall_at_k") or 0)]
print(f"  共 {len(zero)} 条 ({len(zero)*100//len(labeled)}%)")
for s in zero[:10]:
    print(f"    #{s.get('id')} [{s.get('category')}] {str(s.get('question'))[:40]}")
    print(f"        期望: {str(s['ground_truth_docs'])[:96]}")
    got = [x.get("doc_id", "") for x in (s.get("retrieved_docs") or [])][:3]
    print(f"        实召: {str(got)[:96]}")

print()
print("=" * 80)
print("对比：题库扩充前的 24 条标注（多为 doc_*）")
print("=" * 80)
print("  旧口径 83.3% 是「24 条、以精炼条目为主」的成绩；")
print("  新口径 59.5% 是「111 条、含 87 条外部资料」的成绩。")
print("  两者分母不同，**不可直接比较**；后者覆盖面广得多，也更能反映真实检索能力。")
