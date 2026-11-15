"""诊断裁判 30% 解析失败对质量指标的影响。

关键问题：Faithfulness / Context Recall 低，是"回答确实不好"，还是
"裁判判不了 → 被当成不支持"？
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "benchmark" / "reports" / "judge_failure_impact.txt"
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
print(f"文件: {res.name}  样本 {len(samples)}")

print()
print("=" * 76)
print("1) 各样本的 unknown 数量分布")
print("=" * 76)
unks = [s.get("judge_unknowns") or 0 for s in samples]
c = Counter(unks)
for k in sorted(c)[:12]:
    print(f"  unknown={k:<3} 的样本数: {c[k]}")
print(f"  合计 unknown: {sum(unks)}   均值 {sum(unks) / len(unks):.1f}/题")

print()
print("=" * 76)
print("2) 忠实度为 0 的样本，其 unknown 有多少？")
print("=" * 76)
zero_f = [s for s in samples if (s.get("faithfulness") or 0) == 0]
print(f"  忠实度=0 的样本: {len(zero_f)}")
if zero_f:
    zu = [s.get("judge_unknowns") or 0 for s in zero_f]
    print(f"  其中 unknown>0 的: {sum(1 for x in zu if x > 0)}")
    print(f"  这些样本的平均 unknown: {sum(zu) / len(zu):.1f}")

print()
print("=" * 76)
print("3) 忠实度 > 0 的样本（判定成功的）表现如何")
print("=" * 76)
pos_f = [s for s in samples if (s.get("faithfulness") or 0) > 0]
print(f"  忠实度>0 的样本: {len(pos_f)}")
if pos_f:
    vals = [s["faithfulness"] for s in pos_f]
    print(f"  平均忠实度: {sum(vals) / len(vals) * 100:.1f}%")
    print(f"  最高: {max(vals) * 100:.1f}%")

print()
print("=" * 76)
print("4) 上下文召回 / 相关性 的分布")
print("=" * 76)
for key, label in (("context_recall", "Context Recall"),
                   ("context_relevance", "Context Relevance")):
    vals = [s.get(key) for s in samples if s.get(key) is not None]
    if not vals:
        continue
    z = sum(1 for v in vals if v == 0)
    print(f"  {label}: 样本 {len(vals)}, 为 0 的 {z} ({z * 100 // len(vals)}%), "
          f"平均 {sum(vals) / len(vals) * 100:.1f}%")

print()
print("=" * 76)
print("5) 完成度无法判定的样本")
print("=" * 76)
cu = [s for s in samples if s.get("completion_unknown")]
print(f"  共 {len(cu)} 条")
for s in cu[:6]:
    print(f"    #{s.get('id')} [{s.get('category')}] unknown={s.get('judge_unknowns')}")
    print(f"        Q: {str(s.get('question'))[:52]}")

print()
print("=" * 76)
print("6) 裁判一致性分布")
print("=" * 76)
ag = []
for s in samples:
    ag += [a for a in (s.get("judge_agreements") or []) if a is not None]
if ag:
    print(f"  有效一致率样本: {len(ag)}, 均值 {sum(ag) / len(ag):.3f}")
    print(f"  一致率 < 1.0 的: {sum(1 for a in ag if a < 1.0)}")
