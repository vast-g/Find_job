"""验证投递查询工具：不传 user_id 也能拿到当前用户的投递记录。"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "benchmark" / "reports" / "application_tool_check.txt"
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
sys.path.insert(0, str(BASE))

from app.core.context import reset_current_user, set_current_user  # noqa: E402
from app.tools.application_tools import get_user_applications  # noqa: E402


async def main() -> None:
    print("=" * 78)
    print("get_user_applications（user_id 已改为可选 + 请求上下文）")
    print("=" * 78)
    spec = get_user_applications.args.get("user_id", {})
    print(f"  user_id 参数: {spec}")

    print()
    print("  1) 无上下文调用（脚本场景，应回退到最近有投递的用户）")
    r0 = await get_user_applications.ainvoke({})
    print(f"     -> {len(r0)} 条")

    print()
    print("  2) 有上下文调用（正常请求场景）")
    token = set_current_user(1)
    try:
        rows = await get_user_applications.ainvoke({})
    finally:
        reset_current_user(token)
    print(f"     -> {len(rows)} 条投递记录")
    for x in rows:
        print(f"       {x['status']:<6} {str(x['job'])[:30]:<30} "
              f"@ {str(x['company'])[:20]:<20} {x['time'][:10]}")

    print()
    print("  3) 状态分布（验证覆盖了全部枚举，可测出 Agent 能否正确区分）")
    from collections import Counter
    print(f"     {dict(Counter(x['status'] for x in rows))}")


if __name__ == "__main__":
    asyncio.run(main())
