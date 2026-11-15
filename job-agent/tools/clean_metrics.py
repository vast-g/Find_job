"""计算「判定正常」子集的指标，给出可对外引用的可信数字。

报告里的 25.9% 混合了两种样本：
  * 判定正常（unknown=0）—— 反映真实水平
  * 判定全崩（unknown 接近满值）—— 反映裁判故障，不是能力
对外引用应当只用前者，或至少同时说明后者占比。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "benchmark" / "reports" / "clean_metrics.txt"
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

clean = [s for s in samples if (s.get("judge_unknowns") or 0) == 0]
dirty = [s for s in samples if (s.get("judge_unknowns") or 0) > 0]
print(f"  判定正常（unknown=0）: {len(clean)}")
print(f"  判定有欠缺（unknown>0）: {len(dirty)}")


def mean(items, key):
    vals = [s.get(key) for s in items if s.get(key) is not None]
    return (sum(vals) / len(vals), len(vals)) if vals else (None, 0)


print()
print("=" * 78)
print("全体 vs 判定正常子集")
print("=" * 78)
print(f"  {'指标':<20} {'全体':>10} {'判定正常子集':>14} {'子集样本':>10}")
print("  " + "-" * 58)
for key, label in (("task_completion", "任务完成率"),
                   ("faithfulness", "忠实度"),
                   ("context_recall", "上下文召回"),
                   ("context_relevance", "上下文相关性")):
    if key == "task_completion":
        a = [1.0 if s.get("task_completion") else 0.0 for s in samples
             if s.get("task_completion") is not None]
        b = [1.0 if s.get("task_completion") else 0.0 for s in clean
             if s.get("task_completion") is not None]
        av = sum(a) / len(a) * 100 if a else 0
        bv = sum(b) / len(b) * 100 if b else 0
        print(f"  {label:<20} {av:>9.1f}% {bv:>13.1f}% {len(b):>10}")
        continue
    av, _ = mean(samples, key)
    bv, bn = mean(clean, key)
    if av is None:
        continue
    print(f"  {label:<20} {av * 100:>9.1f}% {bv * 100:>13.1f}% {bn:>10}")

print()
print("=" * 78)
print("按类别看「判定正常子集」的忠实度")
print("=" * 78)
from collections import defaultdict
g = defaultdict(list)
for s in clean:
    if s.get("faithfulness") is not None:
        g[s.get("category")].append(s["faithfulness"])
for k in ("面试问答", "岗位推荐", "简历优化", "对抗性"):
    if k in g:
        print(f"  {k:<10} 样本 {len(g[k]):>3}  忠实度 {sum(g[k]) / len(g[k]) * 100:>5.1f}%")

print()
print("=" * 78)
print("这 ~35 条崩掉的样本是什么")
print("=" * 78)
worst = sorted(dirty, key=lambda s: -(s.get("judge_unknowns") or 0))[:10]
for s in worst:
    print(f"  #{s.get('id'):<4} unknown={s.get('judge_unknowns'):<3} "
          f"上下文 {len(s.get('context') or '')} 字符  "
          f"{str(s.get('question'))[:36]}")
