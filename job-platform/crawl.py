# -*- coding: utf-8 -*-
"""
一键爬取国企/央企/事业单位岗位
用法：双击「一键爬取.bat」即可，或命令行 python crawl.py
"""
import json
import urllib.request

BASE = "http://127.0.0.1:8080"


def post(path, data=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["token"] = token
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(BASE + path, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    print("正在登录后端...")
    login = post("/admin/employee/login", {"username": "admin", "password": "123456"})
    if login.get("code") != 1:
        print("登录失败：", login.get("msg"))
        print("请确认后端已在 IDEA 启动（端口 8080）")
        return
    token = login["data"]["token"]
    print("登录成功，开始爬取（按企业性质逐个爬，可能需要 1-3 分钟）...")
    result = post("/admin/crawl/run", token=token)
    print("=" * 40)
    print("爬取完成！本次新增岗位数：", result.get("data"))
    print("刷新小程序「岗位查询」页即可看到新岗位")
    print("=" * 40)


if __name__ == "__main__":
    main()
