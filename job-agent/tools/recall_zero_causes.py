"""区分 Recall@K=0 的两种成因：压根没检索 vs 检索了但没命中。

这两者含义完全不同：
  * 没检索   —— Agent 没调 search_knowledge（可能走别的工具或直接拒答）
  * 检索未中 —— 调了检索，但返回的片段不含标注文档（真正的检索质量问题）

混在一起看会把"Agent 没去查"误算成"检索能力差"。
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "benchmark" / "reports" / "recall_zero_causes.txt"
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
labeled = [s for s in samples if s.get("ground_truth_docs")]

zero = [s for s in labeled if not (s.get("recall_at_k") or 0)]
print(f"结果文件: {res.name}")
print(f"带标注 {len(labeled)} 条, 其中 Recall@K=0 共 {len(zero)} 条 "
      f"({len(zero) * 100 // len(labeled)}%)")

no_retrieval = [s for s in zero if not (s.get("retrieved_docs") or [])]
missed = [s for s in zero if (s.get("retrieved_docs") or [])]

print()
print("=" * 78)
print("成因拆分")
print("=" * 78)
print(f"  A. 压根没检索（retrieved_docs 为空）: {len(no_retrieval)} 条")
print(f"  B. 检索了但没命中标注文档          : {len(missed)} 条")

print()
print("=" * 78)
print("A 类：没检索的用例，看它们调了什么工具")
print("=" * 78)
tools = Counter()
for s in no_retrieval:
    tc = s.get("tool_calls") or []
    tools["(未调任何工具)" if not tc else ",".join(sorted(set(tc)))] += 1
for k, v in tools.most_common():
    print(f"  {v:>3}  {k}")

print()
print("  样例:")
for s in no_retrieval[:6]:
    print(f"    #{s.get('id')} [{s.get('category')}] "
          f"工具={s.get('tool_calls')}")
    print(f"        Q: {str(s.get('question'))[:56]}")
    print(f"        期望检索: {str(s['ground_truth_docs'])[:70]}")

print()
print("=" * 78)
print("B 类：检索了但没命中的用例（真正的检索质量问题）")
print("=" * 78)
for s in missed[:8]:
    print(f"    #{s.get('id')} [{s.get('category')}] {str(s.get('question'))[:48]}")
    print(f"        期望: {str(s['ground_truth_docs'])[:80]}")
    got = [x.get("doc_id", "") for x in (s.get("retrieved_docs") or [])][:2]
    print(f"        实召: {str(got)[:80]}")

print()
print("=" * 78)
print("结论")
print("=" * 78)
print(f"  真正需要改进检索的是 B 类（{len(missed)} 条）；")
print(f"  A 类（{len(no_retrieval)} 条）是 Agent 没去检索，属于**工具选择/策略**问题，")
print("  不是检索链路问题 —— 两者应分开归因。")
