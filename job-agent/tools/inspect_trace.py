"""查看最近若干次请求的 Agent Trace，用于人工核查埋点是否完整。

用法：
    python tools/inspect_trace.py            # 最近 1 次请求
    python tools/inspect_trace.py 3          # 最近 3 次请求
"""
from __future__ import annotations

import sys

import pymysql

sys.stdout.reconfigure(errors="replace")

LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 1

conn = pymysql.connect(
    host="127.0.0.1", port=3306, user="root", password="Root@123456",
    database="job_agent", charset="utf8mb4",
)
cur = conn.cursor()

cur.execute(
    "SELECT request_id, COUNT(*) AS n FROM agent_trace "
    "GROUP BY request_id ORDER BY MAX(id) DESC LIMIT %s",
    (LIMIT,),
)
reqs = cur.fetchall()

if not reqs:
    print("agent_trace 表为空")
    raise SystemExit(0)

for rid, n in reqs:
    print("=" * 78)
    print(f"request_id = {rid}   （{n} 行）")
    print("=" * 78)
    cur.execute(
        "SELECT step, node, input, output, cost_time_ms, error FROM agent_trace "
        "WHERE request_id=%s ORDER BY step",
        (rid,),
    )
    tools = []
    for step, node, inp, out, ms, err in cur.fetchall():
        i = (inp or "").replace("\n", " ")[:38]
        o = (out or "").replace("\n", " ")[:50]
        e = f"  ERROR={err[:40]}" if err else ""
        print(f"  [{step:>2}] {node:<11} {ms if ms is not None else '-':>6}ms  "
              f"in={i!r:<40} out={o!r}{e}")
        if node == "tool":
            tools.append(inp)
    print(f"  → 本请求工具调用：{tools or '（无）'}")
    print()

conn.close()
