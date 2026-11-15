"""直接跑 SQL 验证 JobMapper 修复效果：模拟 MyBatis 将生成的语句，对比修复前后。

这样无需重启后端就能证明修复有效。
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "benchmark" / "reports" / "sql_fix_verify.txt"
OUT.parent.mkdir(parents=True, exist_ok=True)
_fh = OUT.open("w", encoding="utf-8")


class Tee:
    def write(self, s):
        _fh.write(s)

    def flush(self):
        _fh.flush()


sys.stdout = Tee()

import pymysql  # noqa: E402

c = pymysql.connect(host="localhost", port=3306, user="root",
                    password="Root@123456", database="job_platform",
                    charset="utf8mb4")
cur = c.cursor()

ENABLE = 1  # StatusConstant.ENABLE，下面先探一下实际取值

cur.execute("SELECT DISTINCT status FROM job")
statuses = [r[0] for r in cur.fetchall()]
print(f"job.status 取值: {statuses}")


def q_old(city, kw):
    """修复前：city 精确 + 只搜 title"""
    sql = ("SELECT COUNT(*) FROM job j LEFT JOIN company c ON j.company_id=c.id "
           "WHERE j.status=%s")
    args = [ENABLE]
    if city:
        sql += " AND j.city=%s"
        args.append(city)
    if kw:
        sql += " AND j.title LIKE %s"
        args.append(f"%{kw}%")
    cur.execute(sql, args)
    return cur.fetchone()[0]


def q_new(city, kw):
    """修复后：city 模糊 + 关键词跨字段"""
    sql = ("SELECT COUNT(*) FROM job j LEFT JOIN company c ON j.company_id=c.id "
           "WHERE j.status=%s")
    args = [ENABLE]
    if city:
        sql += " AND j.city LIKE %s"
        args.append(f"%{city}%")
    if kw:
        sql += (" AND (j.title LIKE %s OR j.requirement LIKE %s "
                "OR j.description LIKE %s OR c.name LIKE %s)")
        args += [f"%{kw}%"] * 4
    cur.execute(sql, args)
    return cur.fetchone()[0]


print()
print("=" * 80)
print("修复前 vs 修复后：可命中岗位数")
print("=" * 80)
print(f"  {'城市':<6} {'关键词':<10} {'修复前':>7} {'修复后':>7}   增幅")
print("  " + "-" * 62)

CASES = [
    ("北京", "算法"), ("上海", "软件开发"), ("广州", "数据分析"),
    ("北京", "财务"), ("上海", "电气"), ("深圳", "网络安全"),
    ("成都", "人力资源"), ("武汉", "管培生"), ("北京", "法务"),
    ("杭州", "嵌入式"), ("西安", "机械设计"), ("南京", "测试开发"),
    ("重庆", "产品经理"), ("北京", "人工智能"), ("", "材料"),
    ("", "财务"), ("", "管培生"), ("上海", "财务"),
]
zero_before = 0
zero_after = 0
total_before = 0
total_after = 0
for city, kw in CASES:
    o, n = q_old(city, kw), q_new(city, kw)
    total_before += o
    total_after += n
    if o == 0:
        zero_before += 1
    if n == 0:
        zero_after += 1
    mark = ""
    if o == 0 and n > 0:
        mark = f"   <-- 从 0 变为可命中"
    elif n > o:
        mark = f"   +{n - o}"
    print(f"  {city or '不限':<6} {kw:<10} {o:>7} {n:>7}{mark}")

print("  " + "-" * 62)
print(f"  合计命中数：修复前 {total_before} -> 修复后 {total_after}")
print(f"  返回空结果的查询数：修复前 {zero_before}/{len(CASES)} -> "
      f"修复后 {zero_after}/{len(CASES)}")

print()
print("=" * 80)
print("排序效果演示：'财务' 前 8 条（看标题命中的是否排前面）")
print("=" * 80)
cur.execute(
    "SELECT j.title, c.name, j.city, "
    "  CASE WHEN j.title LIKE %s THEN 0 "
    "       WHEN j.requirement LIKE %s THEN 1 "
    "       WHEN c.name LIKE %s THEN 2 ELSE 3 END AS rank "
    "FROM job j LEFT JOIN company c ON j.company_id=c.id "
    "WHERE j.status=%s AND (j.title LIKE %s OR j.requirement LIKE %s "
    "  OR j.description LIKE %s OR c.name LIKE %s) "
    "ORDER BY rank, j.create_time DESC LIMIT 8",
    ("%财务%", "%财务%", "%财务%", ENABLE, "%财务%", "%财务%", "%财务%", "%财务%"),
)
for title, comp, city, rank in cur.fetchall():
    print(f"  [rank={rank}] {str(title)[:34]:<34} | {str(comp)[:18]:<18} | {city}")

c.close()
