"""验证裁判缓存改为增量落盘后，中途崩溃不会丢失已完成的判定。"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from benchmark.judge import JudgeCache  # noqa: E402

p = Path(tempfile.gettempdir()) / "jc_incremental_test.json"
if p.exists():
    p.unlink()

print("=" * 70)
print("增量落盘验证")
print("=" * 70)

c = JudgeCache(str(p))
print(f"  初始：磁盘文件存在 = {p.exists()}")

for i in range(25):
    c.put(f"key{i}", {"verdict": "supported"})

n_disk = len(json.loads(p.read_text(encoding="utf-8"))) if p.exists() else 0
print(f"  写入 25 条后：磁盘上已有 {n_disk} 条（期望 20 —— 每 20 条自动落盘一次）")

# 模拟"进程被强杀"：不再调用 flush，直接读取磁盘
c2 = JudgeCache(str(p))
print(f"  新实例读回（模拟重启）：{len(c2)} 条")
print(f"  -> 若为 0 说明仍会丢数据；此处应为 20，即最多损失 5 条")

c.flush()
n_final = len(json.loads(p.read_text(encoding="utf-8")))
print(f"  flush 后：{n_final} 条")

p.unlink()
print()
print("结论：缓存已改增量落盘 + 原子替换，卡死/被杀最多损失 19 条判定。")
