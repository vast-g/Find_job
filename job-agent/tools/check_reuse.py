"""校验「执行结果」能否被 [J] 复用，并测试从 agent_trace 补回工具输出。

用法：
    python tools/check_reuse.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(errors="replace")
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from benchmark.evaluate import enrich_runs_from_trace, load_dataset, load_runs  # noqa: E402

cases = load_dataset()
runs = load_runs()

ids_c = {c.get("id") for c in cases}
ids_r = {r.get("id") for r in runs} if runs else set()

print("=" * 66)
print("执行结果复用校验")
print("=" * 66)
print(f"  数据集用例      : {len(cases)} 条")
print(f"  已保存执行结果  : {len(runs) if runs else 0} 条")
missing = sorted(ids_c - ids_r)
print(f"  缺失的用例      : {missing if missing else '无'}")
print(f"  可用于 [J] 复用 : {'是' if runs and ids_c <= ids_r else '否'}")

if not runs:
    raise SystemExit(0)

print()
print("=" * 66)
print("从 Agent Trace 补回工具输出（忠实度判定的依据材料）")
print("=" * 66)
before = sum(1 for r in runs if r.get("tool_outputs"))
print(f"  补回前有 tool_outputs : {before}/{len(runs)}")
filled = enrich_runs_from_trace(runs)
after = sum(1 for r in runs if r.get("tool_outputs"))
print(f"  本次补回              : {filled} 条")
print(f"  补回后                : {after}/{len(runs)}")

withctx = sum(1 for r in runs if (r.get("retrieved_docs") or r.get("tool_outputs")))
print()
print(f"  有上下文（可判忠实度）的用例: {withctx}/{len(runs)}"
      f"   [修复前仅 36]")

sample = next((r for r in runs if r.get("tool_outputs")), None)
if sample:
    print()
    print(f"  抽查 #{sample.get('id')}  intent={sample.get('intent')}  "
          f"工具={sample.get('tool_calls')}")
    for i, t in enumerate(sample["tool_outputs"][:2], 1):
        print(f"    工具返回{i}: {t[:88]!r}")

print()
print("=" * 66)
print("裁判调用量重估（上下文补回后会上升，属正常）")
print("=" * 66)
with_gt = sum(1 for c in cases if c.get("ground_truth_docs"))
n_chunks = sum(min(12, len(r.get("retrieved_docs") or [])) for r in runs)
tot = len(runs) * 4 + with_gt * 4 + n_chunks + len(runs)
print(f"  有标准答案要点的用例: {with_gt}")
print(f"  预计裁判调用约 {tot} 次，耗时约 {tot * 4 / 60:.0f} - {tot * 10 / 60:.0f} 分钟")
print()
print("  提示：成功的判定写入缓存，中断后重跑可跳过已完成部分。")
