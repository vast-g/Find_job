"""记忆污染过滤：写入长期记忆前必须过这一层。

绝对不能写入长期记忆的 4 类内容：
1. 闲聊 / 一次性信息（"你好""今天天气""谢谢"）
2. 敏感凭证（密码、token、apikey、身份证、银行卡、手机号）
3. 其他用户数据（对话里带出的他人简历/投递）
4. 时效性强的临时状态（"我明天要面试某公司"这类只在短期记忆保留）

实现策略：规则 + LLM 分类双重过滤。规则兜底（快、确定性），LLM 判模糊边界。
"""
from __future__ import annotations

import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

from app.llm.factory import get_chat_model

# ---- 规则过滤 ----
SECRET_PATTERNS = [
    r"(?i)\b(sk-[a-z0-9]{20,})\b",                 # OpenAI key
    r"(?i)\b(ak-[a-z0-9]{16,})\b",                 # Anthropic key
    # 凭证关键词 + 分隔符(是/为/冒号/等号) + 值。去掉 \b 以兼容中英混排（"的token是"）
    r"(?i)(?:password|passwd|token|secret|apikey|api_key)\s*(?:是|为|[:=])\s*\S+",
    r"(?:密码|令牌|密钥|验证码|口令)\s*(?:是|为|[:：=])\s*\S+",
    r"\b1[3-9]\d{9}\b",                            # 手机号
    r"\b\d{17}[\dXx]\b",                           # 身份证
    r"\b\d{16,19}\b",                              # 银行卡
]

CHITCHAT_KEYWORDS = ["你好", "谢谢", "再见", "在吗", "早上好", "晚安", "哈哈", "ok", "嗯嗯", "收到"]


def rule_filter(text: str) -> bool:
    """返回 True 表示应被过滤（不允许入长期记忆）。"""
    if not text or not text.strip():
        return True
    t = text.strip()
    if len(t) < 4:
        return True
    if t.lower() in CHITCHAT_KEYWORDS:
        return True
    for p in SECRET_PATTERNS:
        if re.search(p, t):
            return True
    return False


# ---- LLM 分类 ----
FILTER_PROMPT = """判断下面这段对话内容是否值得写入用户长期记忆。
只输出 JSON：{"keep": true/false, "reason": "..."}

不写入（keep=false）的情况：
- 闲聊、寒暄、一次性信息
- 包含密码/token/身份证/银行卡等敏感凭证
- 包含其他人的隐私数据
- 只是临时状态，跨会话无价值

写入（keep=true）的情况：
- 用户的求职目标、技能、偏好、简历要点、经历
"""


async def llm_filter(text: str) -> tuple[bool, str]:
    """LLM 二次过滤，返回 (是否保留, 原因)。"""
    m = get_chat_model()
    resp = await m.ainvoke([
        SystemMessage(content=FILTER_PROMPT),
        HumanMessage(content=text),
    ])
    try:
        data = json.loads(resp.content or "{}")
        return bool(data.get("keep", True)), str(data.get("reason", ""))
    except json.JSONDecodeError:
        return True, ""


async def should_keep(text: str) -> bool:
    """入口：先规则，规则能判定就直接返回；否则交给 LLM。"""
    if rule_filter(text):
        return False
    keep, _ = await llm_filter(text)
    return keep
