"""量化求职平台 RAG 索引里"乱码块"的比例。

判别方法：正常中文/英文内容里，可打印字符 + 中文占绝大多数；
而把二进制（UTF-16 字节流、字体数据等）当文本读出来的块，会大量出现
控制字符（\\x00-\\x1f）和不可打印字符。用这个比例做判据。
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(errors="replace")

F = Path(r"C:\Users\Lenovo\Desktop\Find_job\job-agent\data\faiss\documents.jsonl")


def garbage_ratio(s: str) -> float:
    """返回"可疑字符"占比。控制符 + 私用区 + 替换符都算可疑。"""
    if not s:
        return 1.0
    bad = 0
    for ch in s:
        o = ord(ch)
        if o < 0x20 and ch not in "\n\r\t":
            bad += 1
        elif o == 0xFFFD:          # 替换符：解码失败的标志
            bad += 1
        elif 0xE000 <= o <= 0xF8FF:  # 私用区
            bad += 1
    return bad / len(s)


texts: list[str] = []
doc_ids: list[str] = []
with F.open(encoding="utf-8") as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue
        body = o.get("content", o.get("page_content"))
        if body is None:
            continue
        texts.append(str(body))
        doc_ids.append(str((o.get("metadata") or {}).get("doc_id", "")))

n = len(texts)
bad_idx = [i for i, t in enumerate(texts) if garbage_ratio(t) > 0.02]
good_idx = [i for i in range(n) if i not in set(bad_idx)]

print("=" * 72)
print("求职平台 RAG 索引 · 乱码污染量化")
print("=" * 72)
print(f"  总块数            : {n:,}")
print(f"  疑似乱码块        : {len(bad_idx):,}  ({len(bad_idx)/max(1,n)*100:.1f}%)")
print(f"  正常块            : {len(good_idx):,}")
print(f"  乱码块总字符      : {sum(len(texts[i]) for i in bad_idx):,}")

print()
print("  正常块里出现最多的 doc_id 前缀（前 10）：")
pre = Counter(d.split("#")[0] for i, d in enumerate(doc_ids) if i in set(good_idx))
for k, v in pre.most_common(10):
    print(f"    {v:<6} {k}")

print()
print("  乱码块的 doc_id 前缀（前 8）：")
pre2 = Counter(d.split("#")[0] for i, d in enumerate(doc_ids) if i in set(bad_idx))
for k, v in pre2.most_common(8):
    print(f"    {v:<6} {k[:70]!r}")

print()
print("  抽 3 个乱码块看看到底是什么：")
for i in bad_idx[:3]:
    print(f"    doc_id={doc_ids[i][:60]!r}")
    print(f"      {texts[i][:160]!r}")
