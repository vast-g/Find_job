"""核对当前生效的模型配置：API 端点、被测模型、裁判模型，并实测连通性。"""
from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "benchmark" / "reports" / "model_config_check.txt"
OUT.parent.mkdir(parents=True, exist_ok=True)
_fh = OUT.open("w", encoding="utf-8")


class Tee:
    def write(self, s):
        _fh.write(s)

    def flush(self):
        _fh.flush()


sys.stdout = Tee()
sys.path.insert(0, str(BASE))

from app.config import get_settings  # noqa: E402
from benchmark.config import get_eval_settings  # noqa: E402


def mask(k: str) -> str:
    return (k[:10] + "..." + k[-4:]) if k and len(k) > 16 else "(空)"


a = get_settings()
e = get_eval_settings()

print("=" * 74)
print("被测对象（Agent 自己用的模型）")
print("=" * 74)
print(f"  模型      : {a.llm_model}")
print(f"  端点      : {a.openai_base_url}")
print(f"  API Key   : {mask(a.openai_api_key)}")
print(f"  温度      : {a.llm_temperature}")

print()
print("=" * 74)
print("裁判模型（评测打分用）")
print("=" * 74)
print(f"  模型      : {e.judge_model}")
print(f"  端点      : {e.judge_endpoint}")
print(f"  API Key   : {mask(e.judge_api_key)}")
print(f"  max_tokens: {e.judge_max_tokens}")
print(f"  批量判定  : {e.judge_batch}")
print(f"  上下文上限: {e.judge_context_chars}")
print(f"  陈述上限  : {e.judge_max_claims}")

print()
print("=" * 74)
print("独立性检查（裁判必须与被测不同，否则等于自己批改作业）")
print("=" * 74)
same_model = a.llm_model.strip() == e.judge_model.strip()
same_ep = (a.openai_base_url or "").rstrip("/") == (e.judge_endpoint or "").rstrip("/")
print(f"  被测模型 : {a.llm_model}")
print(f"  裁判模型 : {e.judge_model}")
print(f"  模型是否相同 : {'❌ 相同！评测无效' if same_model else '✅ 不同'}")
print(f"  端点是否相同 : {'相同（同一厂商）' if same_ep else '不同'}")
print("  说明：同一端点不代表无效 —— 关键是**模型不同**。"
      "被测是 flash（轻量），裁判是 pro（更强），符合'用更强的模型评判'的常规做法。")

print()
print("=" * 74)
print("连通性实测")
print("=" * 74)


def probe(label: str, model: str, endpoint: str, key: str) -> bool:
    from langchain_core.messages import HumanMessage
    from langchain_openai import ChatOpenAI
    try:
        m = ChatOpenAI(model=model, api_key=key, base_url=endpoint,
                       temperature=0.0, max_tokens=32, timeout=60, max_retries=0)
        r = m.invoke([HumanMessage(content="只回复两个字：可用")])
        c = r.content if isinstance(r.content, str) else str(r.content)
        print(f"  {label:<10} {model:<20} -> OK  {c.strip()[:20]!r}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  {label:<10} {model:<20} -> FAIL {type(exc).__name__}: {str(exc)[:90]}")
        return False


ok_a = probe("被测", a.llm_model, a.openai_base_url, a.openai_api_key)
ok_j = probe("裁判", e.judge_model, e.judge_endpoint, e.judge_api_key)

print()
print("=" * 74)
print("结论")
print("=" * 74)
print(f"  被测可用: {'是' if ok_a else '否'}")
print(f"  裁判可用: {'是' if ok_j else '否'}")
if ok_a and ok_j and not same_model:
    print("  [OK] 配置正确，可以跑评测")
