"""查询 DeepSeek 账户余额，并实测裁判判定的真实花费，估算剩余评测够不够。"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "benchmark" / "reports" / "budget_check.txt"
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
sys.path.insert(0, str(BASE))

import httpx  # noqa: E402

from app.config import get_settings  # noqa: E402

S = get_settings()
KEY = S.openai_api_key
EP = S.openai_base_url.rstrip("/")


def balance() -> dict | None:
    try:
        r = httpx.get(f"{EP}/user/balance",
                      headers={"Authorization": f"Bearer {KEY}"}, timeout=20)
        if r.status_code == 200:
            return r.json()
        print(f"  余额查询失败 HTTP {r.status_code}: {r.text[:160]}")
    except Exception as e:  # noqa: BLE001
        print(f"  余额查询异常: {type(e).__name__}: {str(e)[:120]}")
    return None


print("=" * 74)
print("1) 账户余额")
print("=" * 74)
b = balance()
if b:
    print(json.dumps(b, ensure_ascii=False, indent=2))
else:
    print("  未能获取（该端点可能不支持余额查询）")

print()
print("=" * 74)
print("2) 实测裁判单次判定成本")
print("=" * 74)
from benchmark.config import get_eval_settings  # noqa: E402
from benchmark.judge import Judge  # noqa: E402

es = get_eval_settings()
print(f"  裁判模型: {es.judge_model}")
print(f"  端点    : {es.judge_endpoint}")

j = Judge(samples=1)
# 造一个接近真实长度的上下文
ctx = ("国企面试流程一般分为网申、笔试、面试（一面/二面/终面）、体检、签约。"
       "网申阶段要重点关注岗位JD，简历关键词要与岗位要求匹配。"
       "笔试通常考行测、专业知识、性格测评三部分。") * 6
claims = ["国企面试包含网申环节。", "国企面试必须在一天内完成。",
          "笔试会考行测和专业知识。", "面试结果由面试官当场公布。"]

t0 = time.perf_counter()
before = (j.stats["in_tokens"], j.stats["out_tokens"])
try:
    res = import_asyncio = None
    import asyncio
    res = asyncio.run(j.entailment_batch(ctx, claims))
    dt = time.perf_counter() - t0
    ti = j.stats["in_tokens"] - before[0]
    to = j.stats["out_tokens"] - before[1]
    print(f"  一次批量判定（{len(claims)} 条陈述）")
    print(f"    耗时 {dt:.1f}s  输入 {ti} token  输出 {to} token  合计 {ti + to}")
    print(f"    结果: {res}")
except Exception as e:  # noqa: BLE001
    print(f"  调用失败: {type(e).__name__}: {str(e)[:150]}")
    ti = to = 0

print()
print("=" * 74)
print("3) 全量 200 题裁判成本估算")
print("=" * 74)
# 每题 4 类判定（忠实度/召回/相关性/完成度），前三类已批量
n_cases = 200
per_call = (ti + to) or 1200
calls_per_case = 4
total_tok = n_cases * calls_per_case * per_call

print(f"  估算依据: 每题 {calls_per_case} 次调用 × 单次约 {per_call} token")
print(f"  总计约: {total_tok:,} token ({total_tok / 1e6:.2f}M)")
print()
print("  按 DeepSeek 官方价目折算（输入约 $0.28/M，输出约 $1.10/M；")
print("  这里按输入输出各半的保守比例估算）:")
in_r, out_r = 0.28, 1.10
in_tok = total_tok * 0.75
out_tok = total_tok * 0.25
cost = in_tok / 1e6 * in_r + out_tok / 1e6 * out_r
print(f"    输入 {in_tok / 1e6:.2f}M × ${in_r} + 输出 {out_tok / 1e6:.2f}M × ${out_r}")
print(f"    ≈ ${cost:.2f}")
print()
print("  注：这是保守上限。实际有缓存命中（重跑不重复计费），")
print("      且当前已有部分判定完成。")

print()
print("=" * 74)
print("4) 参考：刚才那次 200 题执行的实测开销")
print("=" * 74)
REPORTS = BASE / "benchmark" / "reports"
res_files = sorted(REPORTS.glob("eval_results_*.json"), key=lambda p: p.stat().st_mtime)
for f in res_files[::-1]:
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        if len(d.get("samples") or []) >= 200:
            s = d.get("summary") or {}
            print(f"  文件: {f.name}")
            print(f"    被测模型总成本: ${s.get('total_cost_usd', 0):.2f}")
            print(f"    输入 token: {s.get('total_prompt_tokens', 0):,}")
            print(f"    输出 token: {s.get('total_completion_tokens', 0):,}")
            break
    except Exception:  # noqa: BLE001
        continue
