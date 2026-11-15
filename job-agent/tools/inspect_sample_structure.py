"""查看结果 JSON 里单个样本的真实字段结构（排查工具调用字段名）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "benchmark" / "reports" / "sample_structure.txt"
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
print(f"文件: {res.name}")
print(f"顶层键: {list(d.keys())}")
samples = d.get("samples") or []
print(f"样本数: {len(samples)}")

s = samples[0]
print()
print("=" * 78)
print("第 1 条样本的全部字段")
print("=" * 78)
for k, v in s.items():
    t = type(v).__name__
    if isinstance(v, list):
        print(f"  {k:<24} list[{len(v)}]  样例={str(v[:2])[:150]}")
    elif isinstance(v, str):
        print(f"  {k:<24} str({len(v)})  {v[:110]!r}")
    else:
        print(f"  {k:<24} {t} = {str(v)[:110]}")

print()
print("=" * 78)
print("统计各类样本的工具调用情况")
print("=" * 78)
from collections import Counter
c = Counter()
for x in samples:
    tc = x.get("tool_calls")
    c[type(tc).__name__] += 1
print(f"  tool_calls 字段类型分布: {dict(c)}")

nonempty = [x for x in samples if x.get("tool_calls")]
print(f"  非空 tool_calls 的样本: {len(nonempty)}/{len(samples)}")
if nonempty:
    x = nonempty[0]
    print(f"    样例 #{x.get('id')}: {str(x['tool_calls'])[:200]}")
    print(f"    类型: {type(x['tool_calls']).__name__}, "
          f"元素类型: {[type(i).__name__ for i in (x['tool_calls'] or [])[:5]]}")
else:
    print("    ⚠️ 全部为空 —— 说明结果文件里确实没存工具调用")
    print("    检查其他可能的字段名：")
    for k in samples[0]:
        if "tool" in k.lower() or "call" in k.lower():
            print(f"      {k} = {str(samples[0][k])[:150]}")
