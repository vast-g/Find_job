"""检查一个"演示时容易被看出来"的短板：简历优化类问题里，
Agent 有没有真的去读用户简历，还是直接给通用建议。

给通用建议 = 没用到系统能力，演示时一眼能看出"不够个性化"。
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "benchmark" / "reports" / "resume_personalization.txt"
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
print(f"结果文件: {res.name}  共 {len(samples)} 条")


def tools_of(s):
    tc = s.get("tool_calls") or []
    return [str(getattr(t, "name", t)) if not isinstance(t, str) else t for t in tc]


for intent in ("resume_opt", "recommend"):
    group = [s for s in samples if s.get("expected_intent") == intent]
    with_resume = [s for s in group if "get_user_resume" in tools_of(s)]
    with_jobs = [s for s in group if "search_jobs" in tools_of(s)]
    none_at_all = [s for s in group if not tools_of(s)]
    print()
    print("=" * 76)
    print(f"意图 {intent} —— 共 {len(group)} 条")
    print("=" * 76)
    print(f"  调用了 get_user_resume : {len(with_resume):>3} 条 "
          f"({len(with_resume) * 100 // max(1, len(group))}%)")
    print(f"  调用了 search_jobs     : {len(with_jobs):>3} 条 "
          f"({len(with_jobs) * 100 // max(1, len(group))}%)")
    print(f"  一个工具都没调         : {len(none_at_all):>3} 条 "
          f"({len(none_at_all) * 100 // max(1, len(group))}%)")

    missing = [s for s in group
               if "get_user_resume" in (s.get("golden_tools") or [])
               and "get_user_resume" not in tools_of(s)]
    print(f"  ⚠️ 期望读简历但没读     : {len(missing):>3} 条 "
          f"({len(missing) * 100 // max(1, len(group))}%)")
    for s in missing[:8]:
        print(f"      #{s.get('id')} 工具={tools_of(s) or '(无)'}")
        print(f"          Q: {str(s.get('question'))[:58]}")

print()
print("=" * 76)
print("工具调用组合分布（resume_opt）")
print("=" * 76)
c = Counter()
for s in samples:
    if s.get("expected_intent") == "resume_opt":
        c["+".join(sorted(set(tools_of(s)))) or "(无工具)"] += 1
for k, v in c.most_common(8):
    print(f"  {v:>3}  {k}")
