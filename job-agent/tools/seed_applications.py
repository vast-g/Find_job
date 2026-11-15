"""给评测用户补投递记录。

## 为什么需要

`application` 表**一行数据都没有**。于是所有「查投递进度」类问题
（题库里有多条，含多轮用例 #422）必然返回空 ——
Agent 既查不到东西，也容易被误判成"不会用工具"。

这与「岗位库缺岗位」「简历表只有占位数据」是同一类问题：
**数据缺失被误读为模型能力不足。**

## 数据设计

状态覆盖全部枚举值，以便测出 Agent 能否正确区分与表述：
    1=已投递  2=已查看  3=面试邀请  4=已录用  5=已拒绝
其中"面试邀请"带 interview_time，用于验证 Agent 是否会主动提示面试时间。

用法：
    python tools/seed_applications.py --dry-run
    python tools/seed_applications.py
    python tools/seed_applications.py --list
    python tools/seed_applications.py --remove
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "benchmark" / "reports" / "seed_applications.txt"
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

TARGET_USER_ID = 1
MARK = "[seed]"

# (岗位标题关键词, 状态, 备注, 面试天数偏移)
PLAN = [
    ("算法", 3, "一面已过，等二面通知", 3),
    ("数据", 2, "HR 说本周内反馈", None),
    ("软件", 5, "岗位要求 3 年经验，应届不匹配", None),
    ("财务", 1, "刚投递，暂无反馈", None),
    ("电气", 4, "已发 offer，待确认入职时间", None),
    ("工程师", 2, "简历已被查看", None),
    ("管理", 1, "走内推渠道投递", None),
    ("测试", 3, "技术面已安排", 5),
]


def connect():
    import pymysql
    return pymysql.connect(host="localhost", port=3306, user="root",
                           password="Root@123456", database="job_platform",
                           charset="utf8mb4")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--remove", action="store_true")
    args = ap.parse_args()

    conn = connect()
    cur = conn.cursor()

    if args.list:
        cur.execute(
            "SELECT a.id, a.status, a.remark, j.title, c.name "
            "FROM application a LEFT JOIN job j ON a.job_id=j.id "
            "LEFT JOIN company c ON j.company_id=c.id WHERE a.user_id=%s "
            "ORDER BY a.id", (TARGET_USER_ID,))
        rows = cur.fetchall()
        print(f"  用户 {TARGET_USER_ID} 的投递记录: {len(rows)} 条")
        for r in rows:
            print(f"    #{r[0]} status={r[1]} {str(r[3])[:26]:<26} @ {str(r[4])[:18]:<18} {r[2]}")
        conn.close()
        return 0

    if args.remove:
        cur.execute("DELETE FROM application WHERE user_id=%s AND remark LIKE %s",
                    (TARGET_USER_ID, f"{MARK}%"))
        print(f"  已删除 {cur.rowcount} 条补入的投递记录")
        conn.commit()
        conn.close()
        return 0

    # ── 取简历 id（外键 NOT NULL，必须有值）──
    cur.execute("SELECT id FROM resume WHERE user_id=%s ORDER BY is_default DESC LIMIT 1",
                (TARGET_USER_ID,))
    row = cur.fetchone()
    if not row:
        print("  ❌ 该用户没有简历记录，无法建投递（resume_id 非空）。请先跑 tools/seed_resume.py")
        conn.close()
        return 1
    resume_id = row[0]
    print(f"  使用简历 id={resume_id}")

    # ── 逐条匹配真实岗位 ──
    cur.execute(
        "SELECT j.id, j.title, c.name FROM job j LEFT JOIN company c ON j.company_id=c.id "
        "WHERE j.status=1 ORDER BY j.id DESC")
    jobs = cur.fetchall()
    print(f"  可选岗位: {len(jobs)} 条")

    cur.execute("SELECT job_id FROM application WHERE user_id=%s", (TARGET_USER_ID,))
    used = {r[0] for r in cur.fetchall()}

    picked = []
    for kw, status, remark, days in PLAN:
        match = next((j for j in jobs if kw in str(j[1]) and j[0] not in used), None)
        if not match:
            match = next((j for j in jobs if j[0] not in used), None)
        if not match:
            continue
        used.add(match[0])
        picked.append((match[0], match[1], match[2], status, remark, days))

    print()
    print("=" * 78)
    print("将要写入的投递记录")
    print("=" * 78)
    for jid, title, comp, status, remark, days in picked:
        itv = f"  面试时间 +{days} 天" if days else ""
        print(f"  status={status}  {str(title)[:30]:<30} @ {str(comp)[:16]:<16} {remark}{itv}")

    if args.dry_run:
        print("\n  --dry-run：未写入")
        conn.close()
        return 0

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    n = 0
    for jid, title, comp, status, remark, days in picked:
        itv = None
        if days:
            itv = time.strftime("%Y-%m-%d %H:%M:%S",
                                time.localtime(time.time() + days * 86400))
        cur.execute(
            "INSERT INTO application (user_id, job_id, resume_id, status, interview_time, "
            "remark, create_time, update_time) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (TARGET_USER_ID, jid, resume_id, status, itv, f"{MARK} {remark}", now, now))
        n += 1

    conn.commit()
    print(f"\n  已写入 {n} 条投递记录")
    cur.execute("SELECT COUNT(1) FROM application")
    print(f"  application 表总量: {cur.fetchone()[0]}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
