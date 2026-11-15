"""验证 AI 对话的全链路：浏览器 → nginx:81 → Java:8080 → Python Agent:8000。

这也是整个 Web 前端的卖点，必须真的跑通一次。
顺带核实子代理的说法：Java 转发层把 Python 侧的 intent/latency_ms/stats 丢了。
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
BASE = "http://127.0.0.1:81"


def b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def jjwt_loose_b64(s: str) -> bytes:
    """复刻 jjwt 0.9.1 的宽松 Base64：只处理完整的 4 字符组。

    已验证：只有按这个推导出的密钥（3 字节 8ad71a）能过后端校验，
    UTF-8 直取和标准 Base64 都是 401。
    """
    keep = s[: (len(s) // 4) * 4]
    return base64.b64decode(keep + "=" * ((4 - len(keep) % 4) % 4))


def sign(payload: dict, key: bytes) -> str:
    h = b64url(json.dumps({"alg": "HS256"}, separators=(",", ":")).encode())
    p = b64url(json.dumps(payload, separators=(",", ":")).encode())
    s = hmac.new(key, f"{h}.{p}".encode(), hashlib.sha256).digest()
    return f"{h}.{p}.{b64url(s)}"


TOKEN = sign({"userId": 1, "exp": int(time.time()) + 3600}, jjwt_loose_b64("itcast"))
H = {"authentication": TOKEN}

print("=" * 72)
print("AI 对话全链路：浏览器 → nginx:81 → Java:8080 → Python Agent:8000")
print("=" * 72)

SESSION = f"web-verify-{int(time.time())}"
QUESTIONS = [
    "帮我推荐几个国企的岗位",
]

for q in QUESTIONS:
    print(f"\n问：{q}")
    t0 = time.time()
    try:
        r = requests.post(BASE + "/api/user/agent/chat",
                          json={"userId": 1, "message": q, "sessionId": SESSION},
                          headers=H, timeout=300, proxies=P)
    except Exception as e:  # noqa: BLE001
        print(f"  ❌ 请求异常 {type(e).__name__}: {e}")
        continue
    dt = time.time() - t0
    print(f"  HTTP {r.status_code}   耗时 {dt:.1f}s")

    if not r.text.lstrip().startswith("{"):
        print("  ❌ 返回的不是 JSON（路径或代理有问题）")
        continue

    j = r.json()
    d = j.get("data") or {}
    print(f"  code = {j.get('code')}")
    print(f"  data 的键 = {list(d.keys())}")
    reply = str(d.get("reply", ""))
    print(f"  reply 长度 = {len(reply)}")
    print()
    print("  ── reply 前 350 字 ──")
    for line in reply[:350].split("\n"):
        print("   " + line)
    if d.get("sources"):
        print(f"\n  sources = {d['sources']}")

print()
print("=" * 72)
print("结论")
print("=" * 72)
print("  ① 四级链路是否打通：看上方的 HTTP / code / reply")
print("  ② Java 转发层丢了哪些字段：对比 data 的键")
print("     期望（Python 侧产出）：sessionId/reply/source/intent/requestId/latencyMs/stats")
print("     实际：见上方 data 的键")

# 历史接口也验一下（前端 onLoad 要恢复会话）
try:
    r = requests.get(BASE + "/api/user/agent/history",
                     params={"sessionId": SESSION}, headers=H, timeout=30, proxies=P)
    j = r.json()
    n = len(j.get("data") or [])
    print(f"\n  /user/agent/history -> HTTP {r.status_code} code={j.get('code')} 历史 {n} 条")
except Exception as e:  # noqa: BLE001
    print(f"\n  history 验证失败：{type(e).__name__}: {e}")
