"""检查 5 条测试用例的判定明细，判断低忠实度是真实现象还是批量格式问题。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "benchmark" / "reports" / "inspect_judge.txt"
OUT.parent.mkdir(parents=True, exist_ok=True)
_fh = OUT.open("w", encoding="utf-8")


class Tee:
    def write(self, s):
        _fh.write(s)

    def flush(self):
        _fh.flush()


sys.stdout = Tee()
sys.path.insert(0, str(BASE))

from benchmark.judge import split_claims  # noqa: E402

rp = sorted((BASE / "benchmark" / "reports").glob("eval_results_*.json"),
            key=lambda p: p.stat().st_mtime)[-1]
raw = json.loads(rp.read_text(encoding="utf-8"))
if isinstance(raw, list):
    results = raw
else:
    results = raw.get("samples") or raw.get("results") or []
print(f"file: {rp.name}  cases: {len(results)}")
if not results and isinstance(raw, dict):
    print(f"  top-level keys: {list(raw.keys())}")
for r in results[:5]:
    print("=" * 76)
    print(f"#{r.get('id')}  intent={r.get('expected_intent')}  route_ok={r.get('route_correct')}")
    print(f"  Q: {str(r.get('question'))[:70]}")
    ans = r.get("answer") or ""
    print(f"  A({len(ans)} chars): {ans[:200]!r}")
    print(f"  faithfulness={r.get('faithfulness')} relevance={r.get('context_relevance')} "
          f"completion={r.get('task_completion')} unknowns={r.get('judge_unknowns')}")
    ctx = r.get("context") or ""
    print(f"  context built: {len(ctx)} chars")
    if ctx:
        print(f"    head: {ctx[:180]!r}")
    print(f"  retrieved_docs={len(r.get('retrieved_docs') or [])} "
          f"tool_outputs={len(r.get('tool_outputs') or [])}")

# 看缓存里的批量判定结果
print()
print("=" * 76)
print("judge cache entries (batch verdicts)")
print("=" * 76)
cache = json.loads((BASE / "benchmark" / "reports" / "judge_cache.json").read_text(encoding="utf-8"))
from collections import Counter  # noqa: E402
cnt = Counter()
for k, v in cache.items():
    if isinstance(v, dict) and isinstance(v.get("verdicts"), list):
        for x in v["verdicts"]:
            cnt[x] += 1
print(f"  total cached batch entries: {sum(1 for v in cache.values() if isinstance(v, dict) and v.get('verdicts'))}")
print(f"  verdict distribution: {dict(cnt)}")
