"""中文分词器：BM25 稀疏检索与 rerank 精排共用。

## 为什么必须单独做这个

langchain `BM25Retriever` 的默认预处理函数是：

    def default_preprocessing_func(text: str) -> List[str]:
        return text.split()

**按空格切。** 中文句子没有空格，于是每个 400 字的片段被切成了
**一个 token**，查询同理。实测：

    输入: 国企面试流程一般分为网申、笔试、面试、体检、签约
    输出: ['国企面试流程一般分为网申、笔试、面试、体检、签约']   ← 整句 1 个 token

后果：BM25 只有"查询与片段字面完全相同"才可能命中，实际等于不工作。
所谓"FAISS + BM25 混合检索"退化成纯稠密检索，稀疏那一路的召回能力全部浪费。

## 设计要点

* 用 jieba 分词，并**丢弃纯标点与空白 token**——标点作 token 只会引入噪声；
* jieba 词表首次调用时惰性加载，之后进程内复用；
* 函数必须定义在**模块顶层**：pickle 按引用序列化函数，
  只有模块级函数才能被 BM25 缓存正确保存与恢复（见 hybrid_retriever 的缓存逻辑）。
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger("app.rag.tokenizer")

# 纯标点/符号（中英文）。这类 token 没有区分度，保留只会稀释 BM25 权重。
_PUNCT_ONLY = re.compile(r"^[\s\W_]+$", re.UNICODE)

_jieba = None
_cache: dict[str, list[str]] = {}


def _get_jieba():
    """惰性加载 jieba（首次导入会读词典，约 0.5-1 秒）。"""
    global _jieba
    if _jieba is None:
        import jieba

        # 关掉 jieba 的初始化日志，避免污染进度输出
        jieba.setLogLevel(logging.WARNING)
        _jieba = jieba
    return _jieba


def tokenize_zh(text: str) -> list[str]:
    """中文分词（BM25 与 rerank 共用）。

    * 过滤空白与纯标点
    * 单字符也保留：中文单字（如"京""沪"）在求职场景有实际区分度
    * 带进程内缓存：BM25 建索引时同一片段只切一次
    """
    if not text:
        return []
    hit = _cache.get(text)
    if hit is not None:
        return hit

    jieba = _get_jieba()
    out = []
    for w in jieba.lcut(text):
        w = w.strip()
        if not w or _PUNCT_ONLY.match(w):
            continue
        out.append(w)

    # 缓存上限：避免长跑进程无限增长（14509 片段 × 400 字 ≈ 数十 MB 量级）
    if len(_cache) < 200_000:
        _cache[text] = out
    else:
        # 超限后不再缓存单条，防止内存无界增长
        pass
    return out


def clear_cache() -> None:
    _cache.clear()


__all__ = ["tokenize_zh", "clear_cache"]
