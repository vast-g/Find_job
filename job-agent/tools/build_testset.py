"""把现有题库与各扩展文件合并成最终题库，并做严格校验。

用法：
    python tools/build_testset.py --check     # 只校验（默认），不改文件
    python tools/build_testset.py --write     # 校验通过后写出题库（会先备份）

## 为什么需要这个闸门

题库一旦有一处标注错误，对应指标就会**长期失真且看不出来**：
  * `golden_tools` 写了意图白名单外的工具 → Tool Accuracy 永远不及格
  * `ground_truth_docs` 写了索引里不存在的 doc_id → Recall@K 恒为 0
    （这个坑真实踩过：数据集引用了不存在的 doc_id，召回率长期为 0 而无人察觉）
  * `id` 重复 → 结果覆盖、Bad Case 归因错位

所以合并前必须逐条校验，宁可报错也不要静默写库。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATASET_DIR = BASE / "benchmark" / "dataset"
# 不可变基线（原始 75 题）：合并**永远从它出发**，而不是从上一轮的产物出发。
# 否则脚本不幂等 —— 第二次运行会把已合并进 testset.jsonl 的扩充题
# 当作"现有题库"再合并一遍，产生大量重复。这个坑真实踩过。
BASE_SET = DATASET_DIR / "testset_base.jsonl"
MAIN = DATASET_DIR / "testset.jsonl"          # 合并产物
INDEX_DOCS = BASE / "data" / "faiss" / "documents.jsonl"
KNOWLEDGE = BASE / "data" / "knowledge.jsonl"

EXTS = [
    ("A 笔试知识", "ext_a_written.json"),
    ("B 面试与真题", "ext_b_interview.json"),
    ("C 岗位与简历", "ext_c_recommend_resume.json"),
    ("D 对抗与多轮", "ext_d_adversarial_multiturn.json"),
]

CATEGORIES = {"岗位推荐", "简历优化", "面试问答", "对抗性"}
# 与 app/core/pipeline.py 的 REACT_TOOLS 保持一致
TOOL_WHITELIST = {
    "recommend": {"get_user_resume", "search_jobs"},
    "resume_opt": {"get_user_resume", "search_jobs", "search_knowledge"},
    "qa": {"search_knowledge", "get_user_applications"},
}
REQUIRED = ("id", "category", "question", "expected_intent", "golden_tools",
            "ground_truth_docs", "expected", "adversarial", "difficulty",
            "success_criteria")

OUT = BASE / "benchmark" / "reports" / "build_testset.txt"
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


def load_jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").split("\n") if l.strip()]


def known_doc_ids() -> set[str]:
    ids: set[str] = set()
    if KNOWLEDGE.exists():
        ids |= {json.loads(l)["doc_id"] for l in
                KNOWLEDGE.read_text(encoding="utf-8").split("\n") if l.strip()}
    if INDEX_DOCS.exists():
        for line in INDEX_DOCS.read_text(encoding="utf-8").split("\n"):
            line = line.strip()
            if line:
                src = json.loads(line)["metadata"].get("doc_id", "").split("#")[0]
                if src:
                    ids.add(src)
    return ids


def validate_case(c: dict, idx: str, known: set[str], errors: list[str],
                  warns: list[str]) -> None:
    tag = f"[{idx}] #{c.get('id')}"
    for f in REQUIRED:
        if f not in c:
            errors.append(f"{tag} 缺字段 {f}")
            return

    if c["category"] not in CATEGORIES:
        errors.append(f"{tag} category 非法: {c['category']}")
    intent = c["expected_intent"]
    if intent not in TOOL_WHITELIST:
        errors.append(f"{tag} expected_intent 非法: {intent}")
        return

    tools = c.get("golden_tools") or []
    bad = set(tools) - TOOL_WHITELIST[intent]
    if bad:
        errors.append(f"{tag} golden_tools 含意图 {intent} 白名单外的工具: {sorted(bad)}")
    if not tools:
        warns.append(f"{tag} golden_tools 为空")

    docs = c.get("ground_truth_docs") or []
    missing = [d for d in docs if d not in known]
    if missing:
        errors.append(f"{tag} ground_truth_docs 含不存在的 doc_id: {missing[:3]}")

    if not isinstance(c.get("expected"), dict) or not (c["expected"].get("关键点")):
        errors.append(f"{tag} expected.关键点 缺失或为空")
    elif not (3 <= len(c["expected"]["关键点"]) <= 5):
        warns.append(f"{tag} 关键点数量 {len(c['expected']['关键点'])}（建议 3-5）")

    if c["adversarial"] not in (0, 1):
        errors.append(f"{tag} adversarial 应为 0 或 1")
    if c["difficulty"] not in (1, 2, 3):
        errors.append(f"{tag} difficulty 应为 1/2/3")
    if not isinstance(c.get("question"), str) or len(c["question"].strip()) < 4:
        errors.append(f"{tag} question 过短")

    setup = c.get("setup")
    if setup is not None:
        if not isinstance(setup, list) or not setup:
            errors.append(f"{tag} setup 应为非空数组")
        else:
            for i, turn in enumerate(setup):
                if not isinstance(turn, dict) or not turn.get("question"):
                    errors.append(f"{tag} setup[{i}] 需为 {{'question': ...}}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="校验通过后写出题库")
    args = ap.parse_args()

    if not BASE_SET.exists():
        print(f"  ❌ 找不到基线文件 {BASE_SET.name}")
        print("     合并必须从不可变基线出发（避免重复合并）。")
        print("     基线 = 原始 75 题（已修正 doc_id 扩展名）。")
        return 1

    main_cases = load_jsonl(BASE_SET)
    print("=" * 84)
    print(f"基线题库（{BASE_SET.name}）: {len(main_cases)} 条")
    print("=" * 84)

    known = known_doc_ids()
    print(f"索引中已知 doc_id: {len(known)} 个")

    all_cases: list[dict] = []
    errors: list[str] = []
    warns: list[str] = []
    per_file: dict[str, int] = {}

    for c in main_cases:
        validate_case(c, "orig", known, errors, warns)
        c.setdefault("reviewed", False)
        all_cases.append(c)
    per_file["现有题库"] = len(main_cases)

    print()
    print("=" * 84)
    print("扩充分片")
    print("=" * 84)
    for label, fname in EXTS:
        p = DATASET_DIR / fname
        if not p.exists():
            print(f"  {label:<16} 缺失（{fname}）")
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{fname} JSON 解析失败: {exc}")
            print(f"  {label:<16} 解析失败: {exc}")
            continue
        if isinstance(data, dict):
            data = data.get("cases") or data.get("data") or []
        print(f"  {label:<16} {len(data):>4} 条")
        per_file[label] = len(data)
        for i, c in enumerate(data):
            c.setdefault("reviewed", False)
            validate_case(c, label, known, errors, warns)
            all_cases.append(c)

    # ── 全局重复检查 ──
    id_counts = Counter(c.get("id") for c in all_cases)
    dup_ids = {k: v for k, v in id_counts.items() if v > 1}
    if dup_ids:
        errors.append(f"id 重复: {dup_ids}")

    q_norm = Counter((c.get("question") or "").strip() for c in all_cases)
    dup_q = {k: v for k, v in q_norm.items() if v > 1 and k}
    if dup_q:
        for q, n in list(dup_q.items())[:5]:
            warns.append(f"问题重复 {n} 次: {q[:40]}")

    # ── 统计 ──
    print()
    print("=" * 84)
    print(f"合并后总计: {len(all_cases)} 条")
    print("=" * 84)
    cat = Counter(c["category"] for c in all_cases)
    print(f"  类别分布   : {dict(cat)}")
    print(f"  意图分布   : {dict(Counter(c['expected_intent'] for c in all_cases))}")
    print(f"  难度分布   : {dict(sorted(Counter(c['difficulty'] for c in all_cases).items()))}")
    print(f"  对抗性     : {sum(1 for c in all_cases if c['adversarial'])} 条")
    print(f"  多轮(setup): {sum(1 for c in all_cases if c.get('setup'))} 条")
    gt = sum(1 for c in all_cases if c.get("ground_truth_docs"))
    print(f"  带检索标注 : {gt} 条 ({gt * 100 // max(1, len(all_cases))}%)"
          f"  <-- 只有这些参与 Recall@K")

    print()
    if warns:
        print(f"  警告 {len(warns)} 条（不阻断）：")
        for w in warns[:12]:
            print(f"    - {w}")
        if len(warns) > 12:
            print(f"    ... 另有 {len(warns) - 12} 条")
    print()
    if errors:
        print(f"  ❌ 校验失败 {len(errors)} 条：")
        for e in errors[:25]:
            print(f"    - {e}")
        if len(errors) > 25:
            print(f"    ... 另有 {len(errors) - 25} 条")
        print()
        print("  未写出题库。请修正上述问题后重跑。")
        return 1

    print("  ✅ 校验全部通过")

    if not args.write:
        print()
        print("  （未加 --write，仅校验，未改动题库）")
        return 0

    # 备份 + 写出
    stamp = time.strftime("%Y%m%d_%H%M%S")
    backup = DATASET_DIR / f"testset_backup_{stamp}.jsonl"
    shutil.copy2(MAIN, backup)

    # 重新编号为连续的 1..N。
    # 各分片作者用的是 101+/201+/301+/401+ 这样的分段号，便于并发生成时避免冲突；
    # 但合并后的题库应当 id 连续（校验器与人工排查都依赖这一点）。
    # 排序后再编号，保证顺序稳定、可复现。
    all_cases.sort(key=lambda c: (c["category"], c.get("difficulty") or 0, c["id"]))
    old_to_new: dict = {}
    for i, c in enumerate(all_cases, 1):
        old_to_new[c["id"]] = i
        c["id"] = i

    with MAIN.open("w", encoding="utf-8") as f:
        for c in all_cases:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    print()
    print(f"  已备份原题库: {backup.name}")
    print(f"  已写出新题库: {MAIN.name}（{len(all_cases)} 条，id 重编号为 1-{len(all_cases)}）")
    print()
    print("  ⚠️ id 已重编号 —— 旧的 regression.jsonl / bad_cases 里引用的 id 会失配，")
    print("     重跑评测前建议先重建回归基线：")
    print("       python -m benchmark.cli baseline")
    return 0


if __name__ == "__main__":
    sys.exit(main())
