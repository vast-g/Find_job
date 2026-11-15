"""诊断最新一次评测为何 100% 失败（延迟 124ms 说明是即时异常）。"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "benchmark" / "reports" / "failure_diagnosis.txt"
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
sys.stderr = Tee()

REPORTS = BASE / "benchmark" / "reports"
files = sorted(REPORTS.glob("eval_results_*.json"), key=lambda p: p.stat().st_mtime)
target = files[-1]
print(f"最新结果文件: {target.name}")
d = json.loads(target.read_text(encoding="utf-8"))
samples = d.get("samples") or []
print(f"样本数: {len(samples)}")

print()
print("=" * 84)
print("错误类型分布")
print("=" * 84)
errs = Counter()
for s in samples:
    e = (s.get("error") or "").strip()
    if not e:
        errs["(无错误)"] += 1
        continue
    errs[e.split(":")[0][:80]] += 1
for k, v in errs.most_common(10):
    print(f"  {v:>4}  {k}")

print()
print("=" * 84)
print("完整错误信息样例（前 3 条）")
print("=" * 84)
shown = 0
for s in samples:
    e = (s.get("error") or "").strip()
    if not e:
        continue
    print(f"\n  #{s.get('id')} [{s.get('category')}] {str(s.get('question'))[:44]}")
    print(f"    {e[:600]}")
    shown += 1
    if shown >= 3:
        break

print()
print("=" * 84)
print("逐条字段检查（看是否所有样本都缺 intent/answer）")
print("=" * 84)
no_intent = sum(1 for s in samples if not s.get("intent"))
no_answer = sum(1 for s in samples if not s.get("answer"))
no_tools = sum(1 for s in samples if not s.get("tool_calls"))
print(f"  无 intent : {no_intent}/{len(samples)}")
print(f"  无 answer : {no_answer}/{len(samples)}")
print(f"  无 tool_calls: {no_tools}/{len(samples)}")
