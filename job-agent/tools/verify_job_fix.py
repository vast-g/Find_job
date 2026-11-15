"""验证 search_jobs 修复：可命中岗位数、降级统计、薪资过滤。

用法：
    python tools/verify_job_fix.py
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "benchmark" / "reports" / "job_fix_verify.txt"
OUT.parent.mkdir(parents=True, exist_ok=True)
_fh = OUT.open("w", encoding="utf-8")


class Tee:
    def write(self, s):
        _fh.write(s)

    def flush(self):
        _fh.flush()


sys.stdout = Tee()
sys.stderr = Tee()
sys.path.insert(0, str(BASE))

logging.basicConfig(level=logging.INFO, format="  [%(name)s] %(levelname)s %(message)s")

from app.tools.job_tools import get_call_stats, reset_call_stats, search_jobs  # noqa: E402

QUERIES = [
    ("财务", None), ("财务", "北京"), ("财务", "上海"),
    ("算法", "北京"), ("数据分析", "广州"), ("电气", None),
    ("材料", None), ("人工智能", "北京"), ("管培生", None),
    ("软件开发", "上海"), ("网络安全", "深圳"), ("测试开发", "南京"),
]


async def main() -> None:
    reset_call_stats()
    print("=" * 78)
    print("search_jobs 修复后效果（后端运行时）")
    print("=" * 78)
    print(f"  {'关键词':<12} {'城市':<8} {'结果数':>6}")
    print("  " + "-" * 40)
    empty = 0
    for kw, city in QUERIES:
        res = await search_jobs.ainvoke({"keywords": kw, "city": city})
        n = len(res)
        if n == 0:
            empty += 1
        mark = "" if n else "   <-- 库里确实没有"
        print(f"  {kw:<12} {str(city or '不限'):<8} {n:>6}{mark}")

    st = get_call_stats()
    print()
    print("=" * 78)
    print("调用统计（关键：降级率必须为 0）")
    print("=" * 78)
    print(f"  总调用      : {st['total']}")
    print(f"  成功有结果  : {st['ok']}")
    print(f"  后端返回空  : {st['backend_empty']}")
    print(f"  降级到兜底  : {st['fallback']}   <-- 非 0 说明后端不可达")
    print(f"  异常        : {st['error']}")
    print()
    if st["fallback"] == 0:
        print("  [OK] 未发生静默降级，所有结果都来自真实岗位库")
    else:
        print("  [!] 发生了降级 —— 请检查 Java 后端是否在 8080 运行")

    print()
    print("=" * 78)
    print("薪资过滤验证（原先 salary_range 是死参数，完全不起作用）")
    print("=" * 78)
    for rng in ["30-60k", "3-5k", None]:
        reset_call_stats()
        res = await search_jobs.ainvoke({"keywords": "财务", "salary_range": rng})
        print(f"  salary_range={str(rng):<8} -> {len(res)} 条")
        for j in res[:2]:
            lo = j.get("salaryMin") or j.get("salary_min")
            hi = j.get("salaryMax") or j.get("salary_max")
            print(f"      {str(j.get('title'))[:32]:<32} 薪资 {lo}-{hi}")


if __name__ == "__main__":
    asyncio.run(main())
