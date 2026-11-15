"""回归门禁：核心指标不得劣化超过容差。

用法：
    python -m benchmark.cli baseline            # 把最近一次结果设为基线
    python -m benchmark.cli gate                # 与基线比较，劣化即退出码 1

CI 集成：PR 触发时运行，核心指标劣化则阻断合并。
这比"跑一下看看"强的地方在于：**历史错过的样本不允许再错**。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from benchmark.config import get_eval_settings

# 受门禁保护的核心指标（越高越好）
GUARDED = [
    ("route_accuracy", "Route Accuracy"),
    ("tool_f1", "Tool F1"),
    ("task_completion_rate", "Task Completion Rate"),
    ("faithfulness", "Faithfulness"),
    ("context_recall", "Context Recall"),
]


def load_baseline() -> dict | None:
    s = get_eval_settings()
    p = Path(s.reports_dir) / "baseline.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def compare(baseline: dict | None, current: dict, tolerance: float) -> dict:
    if baseline is None:
        return {"pass": True, "conclusion": "无基线，本次作为新基线", "deltas": {}}
    bs = baseline.get("summary") or {}
    deltas: dict[str, float | None] = {}
    failed: list[str] = []
    for key, label in GUARDED:
        b, c = bs.get(key), current.get(key)
        if b is None or c is None:
            deltas[key] = None
            continue
        d = c - b
        deltas[key] = round(d, 4)
        if d < -tolerance:
            failed.append(f"{label}({d * 100:+.1f}pp)")
    return {
        "pass": not failed,
        "conclusion": "通过" if not failed else f"指标劣化：{', '.join(failed)}",
        "deltas": deltas,
    }


def set_baseline() -> int:
    from benchmark.report import load_latest_results

    payload = load_latest_results()
    if not payload:
        print("找不到历史结果 JSON，请先运行 run")
        return 1
    s = get_eval_settings()
    Path(s.reports_dir).mkdir(parents=True, exist_ok=True)
    out = Path(s.reports_dir) / "baseline.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"基线已设置：{out}")
    print(f"  样本 {payload.get('summary', {}).get('total')} | "
          f"裁判 {payload.get('judge_model')}")
    return 0


def gate(tolerance: float = 0.02) -> int:
    from benchmark.report import load_latest_results

    payload = load_latest_results()
    if not payload:
        print("找不到历史结果 JSON，请先运行 run")
        return 1
    baseline = load_baseline()
    result = compare(baseline, payload.get("summary") or {}, tolerance)

    print("=" * 64)
    print(f"回归门禁（容差 {tolerance * 100:.1f}pp）")
    print("=" * 64)
    bs = (baseline or {}).get("summary") or {}
    cs = payload.get("summary") or {}
    for key, label in GUARDED:
        b, c = bs.get(key), cs.get(key)
        mark = "—"
        if b is not None and c is not None:
            mark = "PASS" if (c - b) >= -tolerance else "FAIL"
        print(f"  [{mark:4s}] {label:22s} 基线={_fmt(b)} 本次={_fmt(c)}")
    print("=" * 64)
    print(result["conclusion"])
    return 0 if result["pass"] else 1


def _fmt(v) -> str:
    return "—" if v is None else f"{v * 100:.1f}%"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="回归门禁")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("baseline", help="把最近一次结果设为基线")
    g = sub.add_parser("gate", help="与基线比较")
    g.add_argument("--tolerance", type=float, default=0.02)
    args = ap.parse_args(argv)
    return set_baseline() if args.cmd == "baseline" else gate(args.tolerance)


if __name__ == "__main__":
    sys.exit(main())
