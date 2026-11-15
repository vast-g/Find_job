"""验证多轮指代路由修复：setup 之后，追问的意图是否被正确识别。

修复前：pipeline 调 recognize_intent 时没传 history，
        「那上海的呢？」这类指代式追问在路由层看不到上下文，容易误判成 qa。
修复后：把最近 6 条历史一并送入意图识别。
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "benchmark" / "reports" / "multiturn_route_check.txt"
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
sys.path.insert(0, str(BASE))

from benchmark.evaluate import run_case  # noqa: E402

CASES = json.loads(
    (BASE / "benchmark" / "dataset" / "ext_d_adversarial_multiturn.json")
    .read_text(encoding="utf-8")
)
MT = [c for c in CASES if c.get("setup")][:3]


async def main() -> None:
    print("=" * 80)
    print("多轮用例路由检查（含 setup 前置轮）")
    print("=" * 80)
    for c in MT:
        r = await run_case(c)
        expect = c["expected_intent"]
        got = r.get("intent") or "-"
        ok = "OK " if got == expect else "!! "
        print(f"\n  [{ok}] #{c['id']}  期望 {expect} / 实际 {got}")
        for t in c["setup"]:
            print(f"        setup: {t['question']}")
        print(f"        追问 : {c['question']}")
        print(f"        工具 : {r.get('tool_calls')}")
        print(f"        延迟 : {round(r.get('latency_ms', 0))} ms"
              f"   错误: {(r.get('error') or '无')[:60]}")
        ans = (r.get("answer") or "").replace("\n", " ")[:150]
        print(f"        回答 : {ans}")


if __name__ == "__main__":
    asyncio.run(main())
