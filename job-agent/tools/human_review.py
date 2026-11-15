"""人工复核工具：验证 LLM 裁判与人工判断的一致性。

## 为什么需要

面试官会问「你怎么证明你这个大模型判官是正确的」，
业界标准做法是：**人工独立判一遍，算与 LLM Judge 的一致率 / Kappa**。

这个工具把这件事变成两步：
    python tools/human_review.py --make      # 生成复核表（分层抽样）
    # 你在表里填「同意 / 不同意」以及理由
    python tools/human_review.py --score     # 算一致率、Kappa、分歧清单

设计要点：
  * **分层抽样**而不是随机抽 —— 按任务类别分层，保证每类都有样本，
    否则随机抽可能整类落在高一致率的类别上，结论不成立
  * 抽的是 **Task Completion**（二元判定），因为二元判定才能算 Kappa；
    忠实度那种连续值只能算相关系数
  * 复核表里**先给问题与回答、后给裁判判定** —— 顺序上尽量降低锚定效应
  * 评分时同时报告**原始一致率**与 **Cohen's Kappa**
    （原始一致率会被类别不平衡抬高，Kappa 扣掉了随机一致的基线）
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.stdout.reconfigure(errors="replace")

REPORTS = BASE / "benchmark" / "reports"
SHEET = BASE / "benchmark" / "reports" / "human_review_sheet.csv"
RESULT = BASE / "benchmark" / "reports" / "human_review_result.txt"

N_PER_CAT = 5          # 每个类别抽几条


def latest_results() -> Path:
    files = sorted(REPORTS.glob("eval_results_*.json"), key=lambda p: p.stat().st_mtime)
    for f in reversed(files):
        try:
            if len(json.loads(f.read_text(encoding="utf-8")).get("samples") or []) >= 100:
                return f
        except Exception:  # noqa: BLE001
            continue
    raise SystemExit("找不到 200 题的结果文件")


def cmd_make(seed: int) -> int:
    src = latest_results()
    samples = json.loads(src.read_text(encoding="utf-8"))["samples"]
    print(f"结果文件: {src.name}  样本 {len(samples)}")

    by_cat: dict[str, list] = defaultdict(list)
    for s in samples:
        if s.get("task_completion") is not None:
            by_cat[s.get("category") or "?"].append(s)

    rng = random.Random(seed)
    picked: list[dict] = []
    for cat, items in sorted(by_cat.items()):
        rng.shuffle(items)
        take = items[:N_PER_CAT]
        picked += take
        print(f"  {cat:<8} 可判定 {len(items):>3} 条 → 抽 {len(take)} 条")

    # 打乱顺序，避免同类相邻造成的判断惯性
    rng.shuffle(picked)

    with SHEET.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "序号", "case_id", "类别", "问题",
            "Agent 回答（截断）", "裁判判定",
            "你的判断(同意/不同意)", "你的理由", "你给的分(通过/不通过)",
        ])
        for i, s in enumerate(picked, 1):
            ans = (s.get("answer") or "").replace("\n", " ").strip()
            verdict = "通过" if s.get("task_completion") else "不通过"
            w.writerow([
                i, s.get("id"), s.get("category"), s.get("question"),
                ans[:400], verdict, "", "", "",
            ])

    print()
    print(f"✅ 复核表已生成：{SHEET}")
    print(f"   共 {len(picked)} 条（每类 {N_PER_CAT} 条，已打乱顺序）")
    print()
    print("   接下来：")
    print("     1. 用 Excel 打开，逐条读「问题 + Agent 回答」")
    print("     2. 先自己判断「这个回答算不算完成任务」，填最后一列（通过/不通过）")
    print("     3. **填完自己那列之后**，再和「裁判判定」列对照，填「同意/不同意」")
    print("     4. 跑 --score 算一致率")
    return 0


def cohen_kappa(a: list[int], b: list[int]) -> float:
    """二元判定的 Cohen's Kappa。"""
    n = len(a)
    if n == 0:
        return 0.0
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    pa1 = sum(a) / n
    pb1 = sum(b) / n
    pe = pa1 * pb1 + (1 - pa1) * (1 - pb1)
    return 0.0 if pe >= 1 else (po - pe) / (1 - pe)


def cmd_score() -> int:
    if not SHEET.exists():
        print(f"❌ 找不到复核表：{SHEET}\n   先跑 --make")
        return 1

    rows = []
    with SHEET.open("r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            mine = (r.get("你给的分(通过/不通过)") or "").strip()
            if mine:
                rows.append(r)

    if not rows:
        print("❌ 复核表里「你给的分」一列还是空的。")
        print("   请先自己逐条判断并填写（通过 / 不通过），再跑 --score。")
        return 1

    judge, human, agree, diffs = [], [], 0, []
    for r in rows:
        j = 1 if (r.get("裁判判定") or "").strip() == "通过" else 0
        h = 1 if (r.get("你给的分(通过/不通过)") or "").strip() in ("通过", "1", "是") else 0
        judge.append(j)
        human.append(h)
        if j == h:
            agree += 1
        else:
            diffs.append(r)

    n = len(rows)
    po = agree / n
    kappa = cohen_kappa(judge, human)

    lines = [
        "=" * 70,
        "人工复核 vs LLM 裁判 · 一致性报告",
        "=" * 70,
        f"  复核样本数        : {n}",
        f"  原始一致率        : {po * 100:.1f}%   （{agree}/{n}）",
        f"  Cohen's Kappa     : {kappa:.3f}",
        f"  裁判判通过        : {sum(judge)}/{n}",
        f"  人工判通过        : {sum(human)}/{n}",
        "",
    ]

    if kappa >= 0.8:
        lines.append("  解读：Kappa ≥ 0.8 —— 几乎完全一致，裁判可信度充分。")
    elif kappa >= 0.6:
        lines.append("  解读：Kappa 0.6-0.8 —— 高度一致，裁判可用于横向比较。")
    elif kappa >= 0.4:
        lines.append("  解读：Kappa 0.4-0.6 —— 中等一致，需说明分歧集中在哪类样本。")
    else:
        lines.append("  解读：Kappa < 0.4 —— 一致性不足，裁判结论需谨慎使用。")

    if diffs:
        lines += ["", f"分歧样本（{len(diffs)} 条）："]
        for r in diffs:
            lines.append(f"  #{r.get('case_id')} [{r.get('类别')}] "
                         f"裁判={r.get('裁判判定')} 人工={r.get('你给的分(通过/不通过)')}")
            lines.append(f"      问题: {str(r.get('问题'))[:60]}")
            reason = (r.get("你的理由") or "").strip()
            if reason:
                lines.append(f"      你的理由: {reason[:80]}")

    text = "\n".join(lines)
    RESULT.write_text(text, encoding="utf-8")
    print(text)
    print()
    print(f"已保存：{RESULT}")
    return 0


def main() -> int:
    global N_PER_CAT
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--make", action="store_true", help="生成复核表")
    g.add_argument("--score", action="store_true", help="读取填好的表，算一致率")
    ap.add_argument("--seed", type=int, default=20261005, help="抽样随机种子")
    ap.add_argument("--n", type=int, default=N_PER_CAT, help="每类抽几条")
    a = ap.parse_args()
    N_PER_CAT = a.n
    return cmd_make(a.seed) if a.make else cmd_score()


if __name__ == "__main__":
    sys.exit(main())
