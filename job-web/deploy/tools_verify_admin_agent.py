"""验证「管理端 AI 入口」是否真的解决了问题。

关键是这一条对比：
  改之前：管理端 token 调 AI  → 401（因为 AI 只挂在 /user/agent 下，要用户态 token）
  改之后：管理端 token 调 /admin/agent/** → 200

同时确认没破坏原来那条链路（用户态 token 调 /user/agent/** 仍然正常）。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sys
import time

import requests

sys.stdout.reconfigure(errors="replace")
P = {"http": None, "https": None}
BASE = "http://127.0.0.1:8080"

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


def b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def jjwt_loose_b64(s: str) -> bytes:
    keep = s[: (len(s) // 4) * 4]
    return base64.b64decode(keep + "=" * ((4 - len(keep) % 4) % 4))


def sign(payload: dict, key: bytes) -> str:
    h = b64url(json.dumps({"alg": "HS256"}, separators=(",", ":")).encode())
    p = b64url(json.dumps(payload, separators=(",", ":")).encode())
    s = hmac.new(key, f"{h}.{p}".encode(), hashlib.sha256).digest()
    return f"{h}.{p}.{b64url(s)}"


print("=" * 74)
print("管理端 AI 入口验证")
print("=" * 74)

print("\n1) 管理员登录（这是管理员唯一的登录方式）")
r = requests.post(BASE + "/admin/employee/login",
                  json={"username": "admin", "password": "123456"}, timeout=20, proxies=P)
admin_token = (r.json().get("data") or {}).get("token")
check("管理端登录成功", bool(admin_token), (admin_token or "")[:28] + "...")
AH = {"token": admin_token}

print("\n2) ⭐ 改动的重点：管理端 token 能调 AI 了吗")
r = requests.get(BASE + "/admin/agent/history", params={"sessionId": "admin-verify"},
                 headers=AH, timeout=20, proxies=P)
is_json = r.text.lstrip().startswith("{")
check("GET /admin/agent/history 返回 200 且是 JSON",
      r.status_code == 200 and is_json, f"HTTP {r.status_code} {r.text[:60]}")
check("（对比）同一个管理端 token 调 /user/agent/history 仍应被拒",
      requests.get(BASE + "/user/agent/history", params={"sessionId": "x"},
                   headers=AH, timeout=20, proxies=P).status_code == 401,
      "说明管理端 token 确实进不了 /user 那侧 —— 所以我们才需要 /admin/agent")

print("\n3) 管理端 AI 真的能对话（四级链路走通）")
t0 = time.time()
r = requests.post(BASE + "/admin/agent/chat",
                  json={"message": "帮我推荐几个国企岗位", "sessionId": "admin-verify-1"},
                  headers=AH, timeout=300, proxies=P)
dt = time.time() - t0
if r.status_code == 200 and r.text.lstrip().startswith("{"):
    d = r.json().get("data") or {}
    reply = str(d.get("reply", ""))
    check(f"POST /admin/agent/chat 成功（{dt:.0f}s）", len(reply) > 20, f"{len(reply)} 字")
    print("      回答节选：" + reply[:110].replace("\n", " "))
else:
    check("POST /admin/agent/chat 成功", False, f"HTTP {r.status_code} {r.text[:80]}")

print("\n4) 回归：原来用户态那条链路没被破坏")
user_token = sign({"userId": 1, "exp": int(time.time()) + 3600}, jjwt_loose_b64("itcast"))
r = requests.get(BASE + "/user/agent/history", params={"sessionId": "x"},
                 headers={"authentication": user_token}, timeout=20, proxies=P)
check("/user/agent/history 用用户态 token 仍返回 200", r.status_code == 200,
      f"HTTP {r.status_code}")

print("\n5) 鉴权边界：管理端入口不接受用户态 token")
r = requests.get(BASE + "/admin/agent/history", params={"sessionId": "x"},
                 headers={"authentication": user_token}, timeout=20, proxies=P)
check("/admin/agent/** 用用户态 token 被拒（两套鉴权没串）", r.status_code in (401, 403),
      f"HTTP {r.status_code}")

print()
print("=" * 74)
print(f"通过 {len(PASS)} / {len(PASS) + len(FAIL)}")
for f in FAIL:
    print(f"  失败: {f}")
print("=" * 74)
