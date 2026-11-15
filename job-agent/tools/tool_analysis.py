"""用正确字段名（called_tools）重新分析，并量化「对抗性题空 golden_tools」的影响。"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "benchmark" / "reports" / "tool_analysis.txt"
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

# 注意字段名是 called_tools（不是 tool_calls）
def called(s):
    return [str(x) for x in (s.get("called_tools") or [])]


print()
print("=" * 78)
print("1) 简历个性化：期望读简历的用例，实际有没有读")
print("=" * 78)
for intent in ("resume_opt", "recommend"):
    g = [s for s in samples if s.get("expected_intent") == intent]
    need = [s for s in g if "get_user_resume" in (s.get("golden_tools") or [])]
    got = [s for s in need if "get_user_resume" in called(s)]
    print(f"  {intent:<12} 总 {len(g):>3} | 期望读简历 {len(need):>3} | "
          f"真读了 {len(got):>3} ({len(got) * 100 // max(1, len(need))}%)")

print()
print("=" * 78)
print("2) 对抗性题：golden_tools 为空却调了工具的情况")
print("=" * 78)
adv = [s for s in samples if s.get("adversarial")]
empty_gold = [s for s in adv if not (s.get("golden_tools") or [])]
called_something = [s for s in empty_gold if called(s)]
print(f"  对抗性样本        : {len(adv)}")
print(f"  其中 golden 为空  : {len(empty_gold)}")
print(f"  空 golden 却调了工具: {len(called_something)}"
      f"  <- 按现有口径一律算「误调用」，F1=0")
print()
print("  这些用例的问题与实调工具：")
for s in called_something[:12]:
    print(f"    #{s.get('id'):<4} f1={s.get('tool_f1')}  {str(s.get('question'))[:40]}")
    print(f"          实调: {called(s)}")

print()
print("=" * 78)
print("3) 这些「误调用」是否合理？（看回答是否仍正确纠正了前提）")
print("=" * 78)
refuse_kw = ("不存在", "没有", "无法", "不合", "纠正", "不会", "不建议", "不能")
reasonable = 0
for s in called_something:
    ans = s.get("answer") or ""
    hit = any(k in ans for k in refuse_kw)
    if hit:
        reasonable += 1
print(f"  {reasonable}/{len(called_something)} 条的回答中出现了「纠正前提」类措辞")
print("  → 说明 Agent 是「先查证再纠正」，而非盲目迎合。")
print("     把它们一律判为「误调用」会低估真实能力。")

print()
print("=" * 78)
print("4) 各意图的工具调用组合分布")
print("=" * 78)
for intent in ("qa", "recommend", "resume_opt"):
    c = Counter()
    for s in samples:
        if s.get("expected_intent") == intent:
            c["+".join(sorted(set(called(s)))) or "(未调工具)"] += 1
    print(f"  [{intent}]")
    for k, v in c.most_common(6):
        print(f"     {v:>3}  {k}")
