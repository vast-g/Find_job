"""显示知识库的三个来源及其可用性（供重建脚本在开始前展示）。

为什么单独做这个：批处理里用 `findstr` 直接打印 .env 的原始字节，
而 .env 是 UTF-8、控制台是 GBK，中文路径必然显示成乱码，容易让人误以为
"路径配错了"。改由 Python 读取，它会自动适配控制台编码，显示正确。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.stdout.reconfigure(errors="replace")

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from app.config import get_settings  # noqa: E402
from app.rag.parsers import SUPPORTED_EXTENSIONS  # noqa: E402


def count_parseable(root: Path) -> int:
    n = 0
    for _dirpath, _dirnames, filenames in os.walk(root):
        for f in filenames:
            if Path(f).suffix.lower() in SUPPORTED_EXTENSIONS:
                n += 1
    return n


def main() -> int:
    s = get_settings()

    print("  Knowledge sources:")
    print()

    # 1) 精炼知识库
    kb = BASE / "data" / "knowledge.jsonl"
    n_kb = 0
    if kb.exists():
        n_kb = len([l for l in kb.read_text(encoding="utf-8").splitlines() if l.strip()])
    print(f"    [1] data\\knowledge.jsonl   {'OK ' if kb.exists() else 'MISSING'}  {n_kb} entries")

    # 2) 项目内文档
    docs = BASE / "data" / "docs"
    if docs.is_dir():
        n_docs = len([p for p in docs.iterdir()
                      if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS])
        print(f"    [2] data\\docs\\             OK   {n_docs} files")
    else:
        n_docs = 0
        print(f"    [2] data\\docs\\             MISSING")

    # 3) 外部资料合集
    extra = (s.extra_docs_dirs or "").strip()
    if not extra:
        print("    [3] external materials    NOT CONFIGURED")
    else:
        d = Path(extra)
        if d.is_dir():
            print(f"    [3] external materials    OK   {count_parseable(d)} parseable files")
            print(f"        {d}")
        else:
            print(f"    [3] external materials    PATH NOT FOUND")
            print(f"        {d}")

    print()
    print(f"  Index params: RAG_TOP_K={s.rag_top_k}  RAG_CHUNK_SIZE={s.rag_chunk_size}")

    missing = (not kb.exists()) or (not docs.is_dir()) or (extra and not Path(extra).is_dir())
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
