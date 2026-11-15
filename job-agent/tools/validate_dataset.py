"""评测集校验：字段完整性、枚举合法性、工具白名单一致性、doc_id 真实性。

用法：
    python tools/validate_dataset.py [dataset.jsonl]
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.stdout.reconfigure(errors="replace")

# 与代码保持一致（app/core/pipeline.py 的 REACT_TOOLS）
INTENT_TOOLS = {
    "recommend": {"get_user_resume", "search_jobs"},
    "resume_opt": {"get_user_resume", "search_jobs", "search_knowledge"},
    "qa": {"search_knowledge", "get_user_applications"},
}
ALL_TOOLS = set().union(*INTENT_TOOLS.values())
CATEGORIES = {"岗位推荐", "简历优化", "面试问答", "对抗性"}

FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    if not cond:
        FAIL.append(name)


def real_doc_ids() -> set[str]:
    """从实际索引读取真实 doc_id（去掉分块序号）。

    ⚠️ 必须用 `split("\\n")` 而不是 `splitlines()`：
    `splitlines()` 会在 `\\x0c`（换页符）、`\\x85`、`\\u2028` 等字符上也切分，
    而 PDF 提取的文字里常带这些字符 —— 于是 JSON 被拦腰截断，
    报 "Unterminated string" 这种看起来像"文件损坏"的误导性错误。
    （实测踩过：1.4 万片段的索引里能切出 1.47 万行，多出的全是碎片。）
    """
    p = BASE / "data" / "faiss" / "documents.jsonl"
    ids = set()
    if p.exists():
        for line in p.read_text(encoding="utf-8").split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                meta = json.loads(line).get("metadata", {})
            except json.JSONDecodeError:
                continue
            ids.add((meta.get("doc_id") or "").split("#")[0])
    return ids


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE / "benchmark" / "dataset" / "testset.jsonl"
    print("=" * 64)
    print(f"校验评测集：{path}")
    print("=" * 64)
    if not path.exists():
        print("文件不存在")
        return 1

    rows = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as e:
            print(f"  第 {i} 行 JSON 非法：{e}")
            return 1

    docs = real_doc_ids()
    check("总条数 >= 50", len(rows) >= 50, str(len(rows)))
    check("id 唯一", len({r.get("id") for r in rows}) == len(rows))
    check("id 连续从 1 开始", sorted(r.get("id") for r in rows) == list(range(1, len(rows) + 1)))

    cats = Counter(r.get("category") for r in rows)
    check("category 全部合法", set(cats) <= CATEGORIES, str(dict(cats)))
    check("四类均非空", set(cats) == CATEGORIES)

    intents = Counter(r.get("expected_intent") for r in rows)
    check("expected_intent 全部合法", set(intents) <= set(INTENT_TOOLS), str(dict(intents)))

    bad_tools = [r.get("id") for r in rows if not set(r.get("golden_tools") or []) <= ALL_TOOLS]
    check("golden_tools 全部是已注册工具", not bad_tools, f"越界: {bad_tools[:5]}")

    # 最关键：工具必须落在该意图的允许白名单内，否则工具准确率永远上不去
    viol = []
    for r in rows:
        allowed = INTENT_TOOLS.get(r.get("expected_intent"), set())
        if not set(r.get("golden_tools") or []) <= allowed:
            viol.append((r.get("id"), r.get("expected_intent"), r.get("golden_tools")))
    check("golden_tools 落在意图白名单内", not viol, f"违规 {len(viol)} 条: {viol[:3]}")

    bad_docs = [r.get("id") for r in rows if not set(r.get("ground_truth_docs") or []) <= docs]
    check("ground_truth_docs 均为真实 doc_id", not bad_docs, f"不存在: {bad_docs[:5]}")

    with_docs = [r for r in rows if r.get("ground_truth_docs")]
    check("有检索标注的样本数 > 0", len(with_docs) > 0, str(len(with_docs)))

    kp_bad = [r.get("id") for r in rows
              if not (3 <= len((r.get("expected") or {}).get("关键点") or []) <= 6)]
    check("关键点数量在 3-6", not kp_bad, f"异常: {kp_bad[:5]}")

    no_crit = [r.get("id") for r in rows if not (r.get("success_criteria") or "").strip()]
    check("success_criteria 非空", not no_crit, f"缺失: {no_crit[:5]}")

    adv = sum(1 for r in rows if r.get("adversarial"))
    print()
    print("统计：")
    print(f"  总条数        : {len(rows)}")
    print(f"  类别分布      : {dict(cats)}")
    print(f"  意图分布      : {dict(intents)}")
    print(f"  对抗样本      : {adv}")
    print(f"  有检索标注    : {len(with_docs)}")
    print(f"  知识库 doc_id : {len(docs)} 个可用")
    covered = {d for r in rows for d in (r.get('ground_truth_docs') or [])}
    print(f"  被标注引用    : {len(covered)} 个 -> {sorted(covered)}")
    print()
    if FAIL:
        print(f"校验未通过：{FAIL}")
        return 1
    print("校验全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
