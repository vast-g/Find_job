"""岗位库缺口诊断：按评测集的需求，逐条检查"城市 × 岗位方向"的可命中性。

输出可直接指导补数据的清单。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "benchmark" / "reports" / "job_gap_report.txt"
OUT.parent.mkdir(parents=True, exist_ok=True)
_fh = OUT.open("w", encoding="utf-8")


class Tee:
    def write(self, s):
        _fh.write(s)

    def flush(self):
        _fh.flush()


sys.stdout = Tee()

import pymysql  # noqa: E402

conn = pymysql.connect(host="localhost", port=3306, user="root",
                       password="Root@123456", database="job_platform", charset="utf8mb4")
cur = conn.cursor()

# ── 1. 评测集里出现的城市与岗位关键词 ──
CASES = []
for f in ("testset.jsonl", "testset_extra.jsonl"):
    p = BASE / "benchmark" / "dataset" / f
    if not p.exists():
        continue
    for line in p.read_text(encoding="utf-8").split("\n"):
        line = line.strip()
        if line:
            CASES.append(json.loads(line))

CITIES = ["北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "南京",
          "西安", "重庆", "苏州", "天津", "长沙", "郑州", "合肥", "青岛",
          "济南", "福州", "厦门", "大连", "沈阳", "哈尔滨", "昆明", "贵阳"]
ROLES = ["算法", "软件开发", "数据分析", "网络安全", "财务", "人力资源",
         "法务", "嵌入式", "测试开发", "产品经理", "机械设计", "人工智能",
         "电气", "材料", "管培生", "通信", "自动化", "土木", "会计", "运营"]

print("=" * 84)
print("岗位库覆盖矩阵（行=城市，列=岗位方向；数字=可命中岗位数）")
print("=" * 84)
print("  " + "城市".ljust(7) + "".join(r[:4].ljust(6) for r in ROLES))
print("  " + "-" * 80)

gaps: list[tuple[str, str]] = []
city_totals: dict[str, int] = {}
for city in CITIES:
    row = []
    total = 0
    for role in ROLES:
        cur.execute(
            "SELECT COUNT(*) FROM job j LEFT JOIN company c ON j.company_id=c.id "
            "WHERE j.status=1 AND j.city LIKE %s AND (j.title LIKE %s OR "
            "j.requirement LIKE %s OR j.description LIKE %s OR c.name LIKE %s) "
            "AND j.city IS NOT NULL",
            (f"%{city}%", f"%{role}%", f"%{role}%", f"%{role}%", f"%{role}%"),
        )
        n = cur.fetchone()[0]
        total += n
        row.append(n)
        if n == 0:
            gaps.append((city, role))
    city_totals[city] = total
    print(f"  {city:<7}" + "".join(str(v if v else "·").ljust(6) for v in row))

print()
print("=" * 84)
print("城市供给总量")
print("=" * 84)
for city, n in sorted(city_totals.items(), key=lambda x: -x[1]):
    flag = "   <-- 完全没有" if n == 0 else ("   <-- 极少" if n < 5 else "")
    print(f"  {city:<7} {n:>5}{flag}")

print()
print("=" * 84)
print("评测集实际点名的组合（从问题里提取）")
print("=" * 84)
import re  # noqa: E402

asked: list[tuple[str, str]] = []
for c in CASES:
    q = str(c.get("question") or "")
    city = next((x for x in CITIES if x in q), "")
    role = next((r for r in ROLES if r in q), "")
    if city or role:
        asked.append((city, role, q[:44]))

missing_rows = []
for city, role, q in asked:
    if not (city and role):
        continue
    cur.execute(
        "SELECT COUNT(*) FROM job j LEFT JOIN company c ON j.company_id=c.id "
        "WHERE j.status=1 AND (%s='' OR j.city LIKE %s) AND "
        "(j.title LIKE %s OR j.requirement LIKE %s OR j.description LIKE %s OR c.name LIKE %s)",
        (city, f"%{city}%", f"%{role}%", f"%{role}%", f"%{role}%", f"%{role}%"),
    )
    n = cur.fetchone()[0]
    if n == 0:
        missing_rows.append((city, role, q))
    print(f"  {city:<5} {role:<10} -> {n:>4} 条   {q}")

print()
print("=" * 84)
print("需要补的组合（评测点名但库中为 0）")
print("=" * 84)
for city, role, q in missing_rows:
    print(f"  {city} + {role}")
if not missing_rows:
    print("  （无）")

print()
print("=" * 84)
print("参考：库里现有的岗位方向分布（按 title 词频）")
print("=" * 84)
cur.execute("SELECT title FROM job WHERE status=1")
titles = [r[0] or "" for r in cur.fetchall()]
from collections import Counter  # noqa: E402

cnt = Counter()
for t in titles:
    for kw in ["工程师", "管理", "财务", "会计", "电气", "机械", "软件", "数据",
               "算法", "人力", "法务", "运营", "市场", "销售", "技术", "研究",
               "设计", "开发", "测试", "安全", "培训", "采购", "质量"]:
        if kw in t:
            cnt[kw] += 1
for k, v in cnt.most_common(20):
    print(f"  {k:<8} {v:>4}")

conn.close()
