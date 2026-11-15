"""错误分类 + 重试：包装 LangChain BaseChatModel。

错误三类：
- retryable：网络/429/5xx/超时 -> 指数退避重试
- auth_error：401/403 -> 直接抛
- fatal：参数/内容策略 -> 直接抛
"""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableBinding


class LLMError(Exception):
    def __init__(self, message: str, kind: str = "fatal"):
        super().__init__(message)
        self.kind = kind


def classify_error(exc: Exception) -> str:
    text = str(exc).lower()
    code = getattr(exc, "status_code", None) or getattr(exc, "code", None)

    if code in (401, 403):
        return "auth_error"
    if code == 429 or "rate" in text or "quota" in text or "overloaded" in text:
        return "retryable"
    if code is not None and code >= 500:
        return "retryable"
    if "timeout" in text or "connection" in text or "network" in text or "temporarily" in text:
        return "retryable"
    if "content policy" in text or "invalid_request" in text or "not_found" in text or "context length" in text:
        return "fatal"
    return "retryable"


def with_classified_retry(model: BaseChatModel, max_retries: int = 3) -> RunnableBinding:
    """用 LangChain 原生 with_retry 包装，只在可重试错误上重试。"""
    return model.with_retry(
        retry_if_exception_type=(Exception,),
        stop_after_attempt=max_retries + 1,
        wait_exponential_multiplier=1.0,
        wait_exponential_max=10.0,
    )
