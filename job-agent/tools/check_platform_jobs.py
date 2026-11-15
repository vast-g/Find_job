"""查看 Java 后端(`job_platform` 库)的岗位数据，以及 search_jobs 实际能查到什么。"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "benchmark" / "reports" / "platform_jobs.txt"
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

print("=" * 78)
print("1) job_platform 库的表")
print("=" * 78)
cur.execute("SHOW TABLES")
tables = [r[0] for r in cur.fetchall()]
for t in tables:
    try:
        cur.execute(f"SELECT COUNT(*) FROM `{t}`")
        n = cur.fetchone()[0]
        mark = "  <-- 有数据" if n else ""
        print(f"  {t:<34} {n:>8}{mark}")
    except Exception as e:  # noqa: BLE001
        print(f"  {t:<34} err {e}")

job_table = next((t for t in tables if t.lower() in ("job", "jobs")), None)
if not job_table:
    job_table = next((t for t in tables if "job" in t.lower()
                      and "log" not in t.lower() and "user" not in t.lower()), None)

print()
print("=" * 78)
print(f"2) 岗位表 {job_table}")
print("=" * 78)
if job_table:
    cur.execute(f"SHOW COLUMNS FROM `{job_table}`")
    cols = [r[0] for r in cur.fetchall()]
    print(f"  字段: {cols}")
    cur.execute(f"SELECT COUNT(*) FROM `{job_table}`")
    print(f"  岗位总数: {cur.fetchone()[0]}")

    for c in ("city", "company_type", "education", "salary_min", "salary_max",
              "company_name", "job_name"):
        if c in cols:
            cur.execute(f"SELECT `{c}`, COUNT(*) n FROM `{job_table}` "
                        f"GROUP BY `{c}` ORDER BY n DESC LIMIT 10")
            print(f"  {c}: {[(str(r[0])[:22], r[1]) for r in cur.fetchall()]}")

    print()
    print("  最近 8 条岗位:")
    cur.execute(f"SELECT * FROM `{job_table}` ORDER BY 1 DESC LIMIT 8")
    for row in cur.fetchall():
        d = dict(zip(cols, row))
        keep = {k: v for k, v in list(d.items())[:12]}
        print(f"    {str(keep)[:190]}")

    # 模拟 search_jobs 的查询（它调 /user/job/list?keyword=xxx&city=yyy）
    print()
    print("=" * 78)
    print("3) 数据集里那些查询能匹配到多少岗位（按 job_name 关键词）")
    print("=" * 78)
    name_col = next((c for c in ("job_name", "name", "title") if c in cols), None)
    city_col = next((c for c in ("city", "work_city", "area") if c in cols), None)
    probes = [
        ("北京", "算法"), ("上海", "软件开发"), ("", "财务"),
        ("广州", "数据分析"), ("", "电气"), ("成都", "人力资源"),
        ("深圳", "网络安全"), ("武汉", "管培生"), ("北京", "法务"),
        ("杭州", "嵌入式"), ("西安", "机械设计"), ("南京", "测试开发"),
        ("重庆", "产品经理"), ("", "材料"), ("", "人工智能"),
    ]
    for city, kw in probes:
        where, args = [], []
        if city and city_col:
            where.append(f"`{city_col}` LIKE %s")
            args.append(f"%{city}%")
        if kw and name_col:
            where.append(f"`{name_col}` LIKE %s")
            args.append(f"%{kw}%")
        sql = f"SELECT COUNT(*) FROM `{job_table}`"
        if where:
            sql += " WHERE " + " AND ".join(where)
        cur.execute(sql, args)
        n = cur.fetchone()[0]
        flag = "" if n else "   <-- 空"
        print(f"  {city or '不限':<6} {kw:<10} -> {n:>4}{flag}")
else:
    print("  未找到岗位表")

conn.close()
