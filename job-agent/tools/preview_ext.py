"""抽查各扩展分片的内容质量（结构由 build_testset.py 校验，这里看内容）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "benchmark" / "reports" / "ext_preview.txt"
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

D = BASE / "benchmark" / "dataset"
FILES = [
    ("A 笔试知识", "ext_a_written.json"),
    ("B 面试与真题", "ext_b_interview.json"),
    ("C 岗位与简历", "ext_c_recommend_resume.json"),
    ("D 对抗与多轮", "ext_d_adversarial_multiturn.json"),
]

for label, fname in FILES:
    p = D / fname
    print("=" * 84)
    print(f"{label}（{fname}）")
    print("=" * 84)
    if not p.exists():
        print("  尚未生成\n")
        continue
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("cases") or []
    print(f"  共 {len(data)} 条  id 范围 {min(c['id'] for c in data)}-{max(c['id'] for c in data)}")
    step = max(1, len(data) // 3)
    for c in data[::step][:3]:
        print("  " + "-" * 76)
        print(f"  #{c['id']} [{c['category']}/{c['expected_intent']}] 难度{c['difficulty']} "
              f"对抗{c['adversarial']}")
        print(f"  Q: {c['question']}")
        if c.get("setup"):
            print(f"  setup: {' | '.join(t.get('question', '') for t in c['setup'])[:110]}")
        print(f"  工具: {c['golden_tools']}")
        if c.get("ground_truth_docs"):
            print(f"  标注: {c['ground_truth_docs']}")
        kp = (c.get("expected") or {}).get("关键点") or []
        print(f"  要点: {' / '.join(str(k) for k in kp)[:150]}")
        print(f"  验收: {str(c.get('success_criteria'))[:110]}")
    print()
