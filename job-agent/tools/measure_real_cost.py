"""实测裁判判定的真实花费：跑一批真实判定，用余额变化反推单价。

DeepSeek 提供 /user/balance 接口，可以直接观测真实扣费，
比按价目表推算可靠（价目表容易写错，本项目就写成了 OpenAI 的价格）。
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "benchmark" / "reports" / "real_cost_measure.txt"
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
KEY, EP = S.openai_api_key, S.openai_base_url.rstrip("/")

N_CALLS = int(sys.argv[1]) if len(sys.argv) > 1 else 60


def balance() -> float | None:
    try:
        r = httpx.get(f"{EP}/user/balance",
                      headers={"Authorization": f"Bearer {KEY}"}, timeout=20)
        if r.status_code == 200:
            for info in r.json().get("balance_infos", []):
                if info.get("currency") == "CNY":
                    return float(info["total_balance"])
    except Exception as e:  # noqa: BLE001
        print(f"  余额查询失败: {type(e).__name__}: {str(e)[:100]}")
    return None


async def main() -> None:
    print("=" * 74)
    print(f"实测裁判真实花费（执行 {N_CALLS} 次真实判定）")
    print("=" * 74)

    b0 = balance()
    print(f"  执行前余额: ¥{b0}")

    from benchmark.judge import Judge

    j = Judge(samples=1)
    # 用真实长度的上下文
    ctx = ("国企面试流程一般分为网申、笔试、面试（一面/二面/终面）、体检、签约。"
           "网申阶段要重点关注岗位JD，简历关键词要与岗位要求匹配。"
           "笔试通常考行测、专业知识、性格测评三部分。"
           "面试常见形式有结构化、半结构化、无领导小组讨论。") * 5
    claims = ["国企面试包含网申环节。", "国企面试必须在一天内完成。",
              "笔试会考行测和专业知识。", "面试结果由面试官当场公布。"]

    t0 = time.perf_counter()
    done = 0
    for i in range(N_CALLS):
        try:
            await j.entailment_batch(ctx, claims + [f"第{i}次测试陈述。"])
            done += 1
        except Exception as e:  # noqa: BLE001
            print(f"    第 {i} 次失败: {type(e).__name__}: {str(e)[:80]}")
            if done == 0:
                break
    dt = time.perf_counter() - t0
    j.flush()

    ti, to = j.stats["in_tokens"], j.stats["out_tokens"]
    print(f"\n  完成 {done} 次调用，耗时 {dt:.1f}s")
    print(f"  token: 输入 {ti:,} / 输出 {to:,} / 合计 {ti + to:,}")
    print(f"  统计里的判定数: {j.stats['calls']}（含缓存命中 {j.stats['cache_hits']}）")

    # 余额可能延迟更新，稍等再查
    time.sleep(5)
    b1 = balance()
    print(f"\n  执行后余额: ¥{b1}")
    if b0 is not None and b1 is not None:
        delta = b0 - b1
        print(f"  实际扣费: ¥{delta:.2f}")
        if done:
            per = delta / done
            print(f"  单次判定: ¥{per:.4f}")
            # 全量 200 题 ≈ 800 次调用
            need = per * 800
            print()
            print("=" * 74)
            print("全量 200 题裁判预估")
            print("=" * 74)
            print(f"  约 800 次调用 × ¥{per:.4f} = ¥{need:.2f}")
            print(f"  当前余额 ¥{b1} -> "
                  f"{'✅ 够用' if b1 >= need else '❌ 不够，还差 ¥%.2f' % (need - b1)}")
        else:
            print("  未完成任何调用，无法推算单价")


if __name__ == "__main__":
    asyncio.run(main())
