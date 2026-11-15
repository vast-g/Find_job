"""最终验证：浏览器实际走的那条路径（经 nginx:81 → Java → Python）。

前端刚改成调 /admin/agent/**，这里就用管理端 token 走一遍，
确认「登录一次就能用 AI」——不需要任何额外的 token。
"""
from __future__ import annotations

import sys
import time

import requests

sys.stdout.reconfigure(errors="replace")
P = {"http": None, "https": None}
BASE = "http://127.0.0.1:81"          # ← nginx 入口，和浏览器同一条路

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


print("=" * 74)
print("最终验证：经 nginx 的管理端 AI 链路")
print("=" * 74)

print("\n1) 前端静态资源")
r = requests.get(BASE + "/", timeout=10, proxies=P)
check("首页可取", r.status_code == 200 and "<title>" in r.text, f"{len(r.content)} 字节")
for f in ("js/api.js", "js/app.js", "js/charts.js", "css/app.css"):
    rr = requests.get(BASE + "/" + f, timeout=10, proxies=P)
    check(f"{f} 可取", rr.status_code == 200, f"{len(rr.content)} 字节")

print("\n2) 管理员登录（页面右上角那一步）")
r = requests.post(BASE + "/api/admin/employee/login",
                  json={"username": "admin", "password": "123456"}, timeout=20, proxies=P)
token = (r.json().get("data") or {}).get("token")
check("登录成功，拿到管理端 token", bool(token), (token or "")[:26] + "...")
H = {"token": token}

print("\n3) ⭐ 只用这一个 token，就能用 AI")
r = requests.get(BASE + "/api/admin/agent/history",
                 params={"sessionId": "final-verify"}, headers=H, timeout=20, proxies=P)
check("GET /api/admin/agent/history 200", r.status_code == 200 and r.text.lstrip().startswith("{"),
      f"HTTP {r.status_code}")

t0 = time.time()
r = requests.post(BASE + "/api/admin/agent/chat",
                  json={"message": "帮我推荐几个国企岗位", "sessionId": "final-verify-1"},
                  headers=H, timeout=300, proxies=P)
dt = time.time() - t0
if r.status_code == 200 and r.text.lstrip().startswith("{"):
    reply = str((r.json().get("data") or {}).get("reply", ""))
    check(f"POST /api/admin/agent/chat 成功（{dt:.0f}s）", len(reply) > 20, f"{len(reply)} 字")
    print("      节选：" + reply[:100].replace("\n", " "))
else:
    check("POST /api/admin/agent/chat 成功", False, f"HTTP {r.status_code} {r.text[:80]}")

print("\n4) 非 AI 的后端接口仍然正常（回归）")
for p in ("/api/user/stats", "/api/admin/job/page?page=1&pageSize=3"):
    hh = {} if "user" in p else H
    r = requests.get(BASE + p, headers=hh, timeout=20, proxies=P)
    check(f"GET {p.split('?')[0]} 200", r.status_code == 200, f"HTTP {r.status_code}")

print()
print("=" * 74)
print(f"通过 {len(PASS)} / {len(PASS) + len(FAIL)}")
for f in FAIL:
    print(f"  失败: {f}")
print("=" * 74)
