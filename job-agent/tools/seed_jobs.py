"""把补缺岗位数据导入 job_platform 库。

用法：
    python tools/seed_jobs.py --dry-run    # 只校验，不写库（先跑这个）
    python tools/seed_jobs.py              # 实际写入
    python tools/seed_jobs.py --list       # 列出已导入的补缺岗位
    python tools/seed_jobs.py --remove     # 删除所有补缺岗位（按标记）

## 设计要点

* **幂等**：以 (company_id, title, city) 判重，重复执行不会产生重复数据。
* **可识别**：写入的行统一带 `source_url = 'seed://generated'`，
  既区别于爬取的真实数据，也便于一键回滚。
* **先校验后写入**：字段长度、枚举取值范围、薪资区间合法性都在写库前检查，
  避免 MySQL 截断或写入脏数据（`title` 超长会被静默截断，很难发现）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Windows 控制台默认 GBK，输出 emoji/生僻字会抛 UnicodeEncodeError。
# 统一容错，避免"脚本本身崩掉"掩盖真正的校验结果。
sys.stdout.reconfigure(errors="replace")
sys.stderr.reconfigure(errors="replace")

BASE = Path(__file__).resolve().parent.parent
SEED_FILE = BASE / "benchmark" / "dataset" / "seed_jobs.json"
MARKER = "seed://generated"

VALID_CATEGORIES = {5, 6, 7, 8, 9, 10, 11, 12}
VALID_EDUCATION = {"本科", "硕士", "本科及以上", "硕士及以上", "大专", "不限", "博士", "专科及以上"}

# 字段长度上限（与 DDL 一致），超长会在 MySQL 侧被截断或报错
LIMITS = {"title": 64, "city": 32, "education": 16, "tags": 255, "source_url": 500}


def connect():
    import pymysql
    return pymysql.connect(host="localhost", port=3306, user="root",
                           password="Root@123456", database="job_platform",
                           charset="utf8mb4")


def validate(data: dict) -> tuple[list[str], list[str]]:
    """返回 (错误, 警告)。错误会阻止写库。"""
    errors: list[str] = []
    warns: list[str] = []

    companies = data.get("companies") or []
    jobs = data.get("jobs") or []
    if not jobs:
        errors.append("jobs 为空")
    names = {c.get("name") for c in companies}

    for i, j in enumerate(jobs):
        tag = f"jobs[{i}] {str(j.get('title'))[:20]}"
        for field in ("company_name", "title", "description", "city"):
            if not j.get(field):
                errors.append(f"{tag}: 缺字段 {field}")
        if j.get("company_name") not in names:
            errors.append(f"{tag}: company_name 不在 companies 列表里")
        for field, lim in LIMITS.items():
            val = j.get(field)
            if isinstance(val, str) and len(val) > lim:
                errors.append(f"{tag}: {field} 长度 {len(val)} 超过上限 {lim}")
        if j.get("category_id") not in VALID_CATEGORIES:
            errors.append(f"{tag}: category_id={j.get('category_id')} 不在 5-12")
        if j.get("education") and j["education"] not in VALID_EDUCATION:
            warns.append(f"{tag}: education='{j['education']}' 非标准取值")
        if j.get("city") and "-" in str(j["city"]):
            warns.append(f"{tag}: city='{j['city']}' 含区县，与库里格式不一致（不影响匹配）")
        lo, hi = j.get("salary_min"), j.get("salary_max")
        if lo is not None and hi is not None:
            if lo > hi:
                errors.append(f"{tag}: salary_min({lo}) > salary_max({hi})")
            if hi > 100000:
                warns.append(f"{tag}: salary_max={hi} 明显偏高")
        if not isinstance(j.get("salary_min", 0), int) or not isinstance(j.get("salary_max", 0), int):
            warns.append(f"{tag}: 薪资不是整数")

    for c in companies:
        if not c.get("name"):
            errors.append("companies 中有条目缺 name")
    return errors, warns


def coverage(data: dict) -> None:
    """按缺口目标核对覆盖情况。"""
    TARGETS = [
        ("上海", "软件开发"), ("深圳", "网络安全"), ("杭州", "嵌入式"),
        ("西安", "机械设计"), ("南京", "测试开发"),
        ("济南", None), ("沈阳", None), ("哈尔滨", None),
    ]
    jobs = data.get("jobs") or []
    print("  缺口覆盖核对：")
    for city, role in TARGETS:
        hit = [j for j in jobs if j.get("city") == city
               and (role is None or role in str(j.get("title", "")) + str(j.get("description", "")))]
        flag = "OK " if hit else "缺 "
        print(f"    [{flag}] {city} {role or '(任意方向)'}: {len(hit)} 条")
    from collections import Counter
    print("  城市分布：", dict(Counter(j.get("city") for j in jobs)))


def preview(data: dict, n: int = 3) -> None:
    """抽样预览生成内容，写库前人工确认质量。"""
    jobs = data.get("jobs") or []
    if not jobs:
        return
    tl = [len(j.get("title") or "") for j in jobs]
    dl = [len(j.get("description") or "") for j in jobs]
    print(f"  标题长度 平均 {sum(tl) / len(tl):.1f} / 最长 {max(tl)}（上限 64）")
    print(f"  描述长度 平均 {sum(dl) / len(dl):.0f} 字")
    step = max(1, len(jobs) // n)
    for j in jobs[::step][:n]:
        print("  " + "-" * 72)
        print(f"  {j.get('title')}  @  {j.get('company_name')}")
        print(f"  {j.get('city')} | {j.get('education')} | "
              f"{j.get('salary_min')}-{j.get('salary_max')} 元 | {j.get('tags')}")
        print(f"  职责：{(j.get('description') or '')[:170]}")
        print(f"  要求：{(j.get('requirement') or '')[:130]}")


def do_list(cur) -> None:
    cur.execute(f"SELECT COUNT(*) FROM job WHERE source_url=%s", (MARKER,))
    n = cur.fetchone()[0]
    print(f"  已导入的补缺岗位：{n} 条")
    cur.execute("SELECT city, COUNT(*) c FROM job WHERE source_url=%s GROUP BY city ORDER BY c DESC",
                (MARKER,))
    for city, c in cur.fetchall():
        print(f"    {city:<8} {c}")
    cur.execute("SELECT id, title, city FROM job WHERE source_url=%s LIMIT 10", (MARKER,))
    for jid, title, city in cur.fetchall():
        print(f"    #{jid} {title} ({city})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只校验不写库")
    ap.add_argument("--list", action="store_true", help="列出已导入的补缺岗位")
    ap.add_argument("--remove", action="store_true", help="删除所有补缺岗位")
    ap.add_argument("--preview", type=int, default=0, help="抽样预览 N 条生成内容")
    args = ap.parse_args()

    if not SEED_FILE.exists():
        if args.list or args.remove:
            conn = connect()
            with conn.cursor() as cur:
                if args.list:
                    do_list(cur)
                else:
                    cur.execute("DELETE FROM job WHERE source_url=%s", (MARKER,))
                    print(f"  已删除 {cur.rowcount} 条补缺岗位")
                conn.commit()
            conn.close()
            return 0
        print(f"找不到 {SEED_FILE}")
        return 1

    data = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    jobs = data.get("jobs") or []
    companies = data.get("companies") or []
    print(f"  读取 {SEED_FILE.name}：岗位 {len(jobs)} 条，公司 {len(companies)} 家")

    errors, warns = validate(data)
    if warns:
        print(f"\n  警告 {len(warns)} 条（不阻止写入）：")
        for w in warns[:15]:
            print(f"    - {w}")
    if errors:
        print(f"\n  ❌ 校验失败 {len(errors)} 条：")
        for e in errors[:25]:
            print(f"    - {e}")
        return 1
    print("  ✅ 校验通过")
    coverage(data)
    if args.preview:
        preview(data, args.preview)

    conn = connect()
    cur = conn.cursor()

    if args.list:
        do_list(cur)
        conn.close()
        return 0

    if args.remove:
        cur.execute("DELETE FROM job WHERE source_url=%s", (MARKER,))
        print(f"\n  已删除 {cur.rowcount} 条补缺岗位")
        conn.commit()
        conn.close()
        return 0

    if args.dry_run:
        print("\n  --dry-run：未写入数据库")
        conn.close()
        return 0

    # ── 公司：按名称查找，缺失则创建 ──
    cur.execute("SELECT id, name FROM company")
    existing = {name: cid for cid, name in cur.fetchall()}
    created_companies = 0
    for c in companies:
        name = c["name"]
        if name in existing:
            continue
        cur.execute(
            "INSERT INTO company (name, type, city, logo, description, status, create_time, update_time) "
            "VALUES (%s,%s,%s,%s,%s,1,NOW(),NOW())",
            (name, c.get("type") or "国有企业", c.get("city"), "", c.get("description")),
        )
        existing[name] = cur.lastrowid
        created_companies += 1
    print(f"\n  新增公司 {created_companies} 家（复用已有 {len(companies) - created_companies} 家）")

    # ── 岗位：以 (company_id, title, city) 判重，保证幂等 ──
    cur.execute("SELECT company_id, title, city FROM job")
    seen = {(a, (b or "").strip(), (c or "").strip()) for a, b, c in cur.fetchall()}

    inserted = skipped = 0
    for j in jobs:
        key = (existing[j["company_name"]], j["title"].strip(), str(j.get("city") or "").strip())
        if key in seen:
            skipped += 1
            continue
        cur.execute(
            "INSERT INTO job (company_id, category_id, title, description, requirement, "
            "salary_min, salary_max, city, education, tags, status, view_count, apply_count, "
            "deadline, create_time, update_time, create_user, update_user, source_url) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,0,0,NULL,NOW(),NOW(),1,1,%s)",
            (key[0], j.get("category_id"), j["title"], j.get("description"),
             j.get("requirement"), j.get("salary_min"), j.get("salary_max"),
             j.get("city"), j.get("education"), j.get("tags"), MARKER),
        )
        seen.add(key)
        inserted += 1

    conn.commit()
    print(f"  新增岗位 {inserted} 条，跳过重复 {skipped} 条")
    cur.execute("SELECT COUNT(*) FROM job")
    print(f"  岗位库总量：{cur.fetchone()[0]} 条")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
