"""评测专用配置。

与被测系统的 `app/config.py` 分开：评测参数的改动不应该影响线上行为，
反之亦然。唯一共用的是 LLM 接入信息（base_url / api_key）。

## 裁判模型的选择

被测 Agent 用 `deepseek-v4.1-flash`（百炼）。裁判**必须换一个模型**，
否则就是自己批改自己的作业 —— 原实现的 `benchmark/judge.py` 直接从
`app.llm.factory.get_chat_model()` 取模型，与被测完全同一个实例，
这样得到的"正确率"没有任何说服力。

这里默认用 `glm-5.3`（百炼，与被测模型同端点但不同厂商、不同模型）。
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent  # job-agent/


class EvalSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── 被测系统 ──
    # 评测必须走进程内记忆：每条用例独立 session，天然隔离且不依赖 Redis
    memory_backend: str = "memory"

    # ── 裁判 ──
    judge_model: str = "glm-5.3"
    # 裁判可独立于被测系统使用不同厂商/端点。
    # 典型场景：被测在百炼、裁判在官方 API（或本机 Ollama）。
    # 留空则回落到被测系统的 OPENAI_BASE_URL / OPENAI_API_KEY。
    judge_url: str = ""
    judge_key: str = ""
    judge_temperature: float = 0.0
    # glm-5.3 是推理模型，但**正常调用的思考量只有 60-200 token**
    # （实测：忠实度长上下文输入 2486 token，输出仅 62 token）。
    # 额度设太大没有收益，反而让偶发的"思考死循环"烧掉更多：
    # 实测小提示词也能吃满 8192 且不终止，单次耗时约 128 秒。
    # 这里给约 20 倍余量即可；遇死循环由重采样兜住（见 judge._vote）。
    judge_max_tokens: int = 4096
    # 单次裁判超时。正常调用 2-3 秒，死循环约 128 秒；
    # 设小可让病态调用更快失败，避免整轮评测被拖死。
    judge_timeout: int = 60
    # 自一致性采样次数：1=关闭（快），3=多数票（稳）
    judge_samples: int = 1

    # ── 裁判 token 成本控制 ──
    # 调试记录（决定了这组默认值）：
    #   * glm-5.3 是推理模型，成本极高：忠实度逐条判定时每条都要重发完整上下文，
    #     75 题实测约 2.54M token；且批量格式下思考量暴涨、偶发死循环。
    #   * deepseek-v4-pro 无推理开销，批量判定实测 0.6-4.7s、单次数百 token，
    #     全量约 0.25M token，额度不再是约束。
    # 因此上下文上限恢复到 2500（兼顾判定质量），并默认开启批量。
    judge_context_chars: int = 2500
    # 每题最多判定几条陈述（忠实度是比率，抽样即可代表，无需逐句穷举）
    judge_max_claims: int = 8
    # 是否启用批量判定（一次调用判多条）。
    # deepseek 系列批量稳定且省数倍调用次数 → 默认开启。
    # ⚠️ 若换回 glm-5.3 这类推理模型，务必改为 false，否则会显著变慢、变贵甚至死循环。
    judge_batch: bool = True
    judge_cache_file: str = str(BASE_DIR / "benchmark" / "reports" / "judge_cache.json")

    # ── 数据集 / 产物 ──
    dataset_file: str = str(BASE_DIR / "benchmark" / "dataset" / "testset.jsonl")
    dataset_extra_file: str = str(BASE_DIR / "benchmark" / "dataset" / "testset_extra.jsonl")
    reports_dir: str = str(BASE_DIR / "benchmark" / "reports")
    badcases_dir: str = str(BASE_DIR / "benchmark" / "bad_cases")
    regression_file: str = str(BASE_DIR / "benchmark" / "dataset" / "regression.jsonl")

    # ── 执行 ──
    concurrency: int = 4
    # 每条用例跑完是否清空该 session 的历史（评测应当逐题独立）
    isolate_sessions: bool = True
    # 单条用例的整体超时（秒），兜住 Agent 内部超时失效的情况
    case_timeout: int = 180

    # ── 判定阈值（用于 Bad Case 归因）──
    faithfulness_floor: float = 0.6
    context_recall_floor: float = 0.6

    @property
    def judge_endpoint(self) -> str:
        """裁判端点。优先用 JUDGE_URL，其次被测系统的 OpenAI 兼容端点。

        注意：pydantic-settings 会把 .env 读进 Settings 对象，但**不会**写进
        os.environ。所以必须从 app 的 Settings 取，不能只靠 os.getenv，
        否则会出现"key 明明配了却报缺失"。
        """
        if self.judge_url:
            return self.judge_url
        env = os.getenv("OPENAI_BASE_URL")
        if env:
            return env
        try:
            from app.config import get_settings

            return get_settings().openai_base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        except Exception:  # noqa: BLE001
            return "https://dashscope.aliyuncs.com/compatible-mode/v1"

    @property
    def judge_api_key(self) -> str:
        if self.judge_key:
            return self.judge_key
        env = os.getenv("OPENAI_API_KEY")
        if env:
            return env
        try:
            from app.config import get_settings

            return get_settings().openai_api_key or ""
        except Exception:  # noqa: BLE001
            return ""

    def ensure_dirs(self) -> None:
        for d in (self.reports_dir, self.badcases_dir):
            Path(d).mkdir(parents=True, exist_ok=True)


@lru_cache
def get_eval_settings() -> EvalSettings:
    return EvalSettings()
