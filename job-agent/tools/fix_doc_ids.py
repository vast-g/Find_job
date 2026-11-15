"""修正题库中 ground_truth_docs 带了文件扩展名的 doc_id。

## 问题

索引里的 doc_id 是**去掉扩展名**的相对路径（如 `面试准备指南`），
但题库里有 3 条写成了 `面试准备指南.txt` / `央企校招注意事项.docx`。

后果很隐蔽：`match_docs()` 按前缀比对时永远匹配不上，
这 3 条题的 Recall@K 恒为 0 且**不会有任何报错** ——
表现为"检索质量比实际差"，而不是"数据出错"。

用法：
    python tools/fix_doc_ids.py --dry-run
    python tools/fix_doc_ids.py
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
MAIN = BASE / "benchmark" / "dataset" / "testset.jsonl"
INDEX = BASE / "data" / "faiss" / "documents.jsonl"
KNOW = BASE / "data" / "knowledge.jsonl"

OUT = BASE / "benchmark" / "reports" / "fix_docids.txt"
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

# 已知且只存在"去扩展名"形态的文档后缀
KNOWN_EXTS = (".txt", ".docx", ".doc", ".pdf", ".md")


def known_ids() -> set[str]:
    ids: set[str] = set()
    if KNOW.exists():
        ids |= {json.loads(l)["doc_id"] for l in
                KNOW.read_text(encoding="utf-8").split("\n") if l.strip()}
    if INDEX.exists():
        for line in INDEX.read_text(encoding="utf-8").split("\n"):
            line = line.strip()
            if line:
                ids.add(json.loads(line)["metadata"].get("doc_id", "").split("#")[0])
    return ids


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    known = known_ids()
    cases = [json.loads(l) for l in MAIN.read_text(encoding="utf-8").split("\n") if l.strip()]

    print("=" * 80)
    print("扫描带扩展名的 doc_id")
    print("=" * 80)
    changes: list[tuple[int, str, str]] = []
    for c in cases:
        docs = c.get("ground_truth_docs") or []
        new_docs = []
        for d in docs:
            if d not in known and d.endswith(KNOWN_EXTS):
                stripped = d.rsplit(".", 1)[0]
                if stripped in known:
                    changes.append((c["id"], d, stripped))
                    new_docs.append(stripped)
                    continue
            new_docs.append(d)
        if new_docs != docs:
            c["ground_truth_docs"] = new_docs

    if not changes:
        print("  未发现需要修正的 doc_id")
        return 0
    for cid, old, new in changes:
        print(f"  #{cid}: {old!r} -> {new!r}")

    if args.dry_run:
        print("\n  --dry-run：未写入")
        return 0

    stamp = time.strftime("%Y%m%d_%H%M%S")
    backup = MAIN.parent / f"testset_backup_{stamp}.jsonl"
    shutil.copy2(MAIN, backup)
    with MAIN.open("w", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"\n  已备份: {backup.name}")
    print(f"  已修正 {len(changes)} 处，写回 {MAIN.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
