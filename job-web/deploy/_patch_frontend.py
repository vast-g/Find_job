"""把前端从「用户态 token + /user/agent」切到「管理端 token + /admin/agent」。

背景：后端已经补了 /admin/agent 入口（管理端拦截器），管理控制台本来就已经
用 admin/123456 登录并持有管理端 token，所以**不再需要演示登录那套绕行**。

这个脚本做机械替换，只改"接口路径 + 守卫条件"，不动 UI 结构；
每一处替换都断言命中次数，避免静默改错（宁可报错也不要悄悄少改/多改）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(errors="replace")

W = Path(r"C:\Users\Lenovo\Desktop\Find_job\job-web")

# (文件, 原串, 新串, 期望命中次数)
PATCHES = [
    # ── api.js：把剩下的 /user/agent/history 换成管理端入口 ──
    ("js/api.js",
     "await request('/user/agent/history', {",
     "await request('/admin/agent/history', {",
     3),
    # ── app.js：AI 相关改用管理端路径 ──
    ("js/app.js",
     "await Api.request('/user/agent/feedback', {",
     "await Api.request('/admin/agent/feedback', {",
     1),
    ("js/app.js",
     "path: '/user/agent/history?sessionId=health'",
     "path: '/admin/agent/history?sessionId=health'",
     1),
    ("js/app.js",
     "errorDetail: '/user/agent/chat 不在免鉴权白名单里，必须带请求头 authentication。',",
     "errorDetail: 'AI 接口需要管理端 token（请求头 token）。请先在右上角用 admin/123456 登录。',",
     1),
]

ok = True
for fname, old, new, expect in PATCHES:
    p = W / fname
    text = p.read_text(encoding="utf-8")
    n = text.count(old)
    mark = "OK " if n == expect else "!! "
    print(f"  [{mark}] {fname}: 命中 {n} 处（期望 {expect}）  {old[:52]}")
    if n != expect:
        ok = False
        continue
    p.write_text(text.replace(old, new), encoding="utf-8")

print()
print("全部命中" if ok else "有未按预期命中的项，请人工检查")
