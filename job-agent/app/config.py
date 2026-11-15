"""全局配置，从环境变量 / .env 读取。"""
import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # MySQL
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = ""
    mysql_db: str = "job_agent"

    # LLM
    llm_provider: str = "qwen"          # openai / anthropic / gemini / qwen
    llm_model: str = "qwen3:4b"
    llm_temperature: float = 0.2
    openai_api_key: str = ""
    openai_base_url: str = ""
    anthropic_api_key: str = ""
    google_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"

    # Embedding
    embedding_provider: str = "ollama"   # ollama / sentence-transformers
    embedding_model: str = "nomic-embed-text"
    # 保持嵌入模型常驻内存，避免构建大索引期间 Ollama 反复卸载/重载。
    # 这点很关键：Ollama 默认 5 分钟不用就卸载模型，重载会为模型重新分配一个
    # **随机内部端口**（llama-server，如 52166），持有旧端口引用的客户端会连不上，
    # 报 "actively refused"。构建 1.4 万片段要 20 分钟，几乎必然踩到这个坑。
    # 单位：秒（langchain-ollama 的 keep_alive 只接受整数）；-1 表示永不卸载。
    embedding_keep_alive: int = 1800

    # RAG
    faiss_index_dir: str = "./data/faiss"
    rag_top_k: int = 5
    rag_chunk_size: int = 200
    # 额外资料目录（分号分隔，可多个）：原地索引，不复制文件。
    # 用于挂载项目外部的大型资料合集，例如「国企招聘笔试面试资料题库」。
    extra_docs_dirs: str = ""
    # 是否启用 CrossEncoder 精排（需联网下载模型，离线环境置 false）
    rerank_use_cross_encoder: bool = False
    # BM25 是否使用中文分词（jieba）。
    #   true  —— 正确：中文必须分词，否则 BM25 每个片段只切成 1 个 token 而失效
    #   false —— 还原为 langchain 默认的按空格切分（中文下等于关闭稀疏检索）
    # 保留开关是为了做 A/B 对照，验证分词修复到底带来多少提升。
    bm25_chinese_tokenizer: bool = True

    # 终止条件
    max_react_steps: int = 10
    timeout_seconds: int = 30
    max_budget_usd: float = 0.05

    # 计价覆盖（每 1K token，美元）。
    #
    # 不设置时按 app/core/stats.py 的 MODEL_PRICE_PER_1K 按**模型名**匹配。
    # 之所以做成可覆盖：模型价格会变，而且同一个 provider 下不同模型价格差很多
    # （百炼上 deepseek 和 qwen-max 就不是一个量级）。
    # 价格算错的后果不只是报表不准 —— 预算护栏会误判并把已生成的答案丢掉，
    # 所以宁可留一个显式覆盖口。
    llm_price_in_per_1k: float | None = None
    llm_price_out_per_1k: float | None = None

    # 记忆
    summary_interval: int = 5
    short_term_turns: int = 30
    # 会话处理互斥：租期由后台心跳续期，总请求时间单独受限。
    memory_lock_ttl: int = 30
    memory_request_timeout: float = 180.0
    redis_socket_timeout: float = 3.0
    redis_max_connections: int = 50

    # Redis（短期记忆）
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_ttl: int | None = 604800
    # 短期记忆后端：redis | memory
    #   redis  —— 生产默认，跨进程共享、带 TTL
    #   memory —— 进程内存储，用于评测 / 容器化 / 本机未装 Redis 的场景
    # 评测时必须用 memory：每条用例独立 session，天然隔离，且不依赖外部服务。
    memory_backend: str = "redis"

    @property
    def mysql_url(self) -> str:
        # 账号/密码可能含 @ : / 等特殊字符，需 URL 编码
        return (
            f"mysql+asyncmy://{quote_plus(self.mysql_user)}:{quote_plus(self.mysql_password)}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_db}?charset=utf8mb4"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


# 敏感键：值不同时只显示尾 4 位，避免把 key 打进日志
_SENSITIVE = {"OPENAI_API_KEY", "JUDGE_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"}

# **评测框架故意覆盖**的键，不算冲突：
#   MEMORY_BACKEND —— benchmark/cli.py 的 _setup() 会 setdefault 成 memory，
#                     因为评测要求每条用例独立 session、不依赖 Redis。
# 除此之外的任何覆盖都值得警惕。
_INTENTIONAL_OVERRIDES = {"MEMORY_BACKEND"}


def _mask(name: str, value: str) -> str:
    if name.upper() in _SENSITIVE and len(value) > 8:
        return "****" + value[-4:]
    return value


def check_env_overrides() -> list[tuple[str, str, str]]:
    """检查 `.env` 里哪些键被**同名环境变量**覆盖了。

    返回 [(键名, 环境变量值, .env 值), ...]（已脱敏）。

    ## 为什么必须检查

    pydantic-settings 的优先级是 **环境变量 > .env 文件**。
    踩过的坑：用户级环境变量里残留着上一家厂商的 `OPENAI_API_KEY`，
    优先级高于 `.env`，于是"配置明明改对了却仍用旧 key"，
    表现为 **200 条评测用例全部 401**，而错误信息写着
    "Your api key: ****1929 is invalid" —— 很容易被误判成
    "key 失效了"，而不是"拿的不是 .env 里那个 key"。

    这类问题**不会报错、不会警告**，只能靠主动比对发现。
    """
    env_path = Path(__file__).resolve().parent.parent / ".env"
    out: list[tuple[str, str, str]] = []
    if not env_path.exists():
        return out
    for raw in env_path.read_text(encoding="utf-8").split("\n"):
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if key == "JUDGE_KEY":
            # JUDGE_KEY 是评测侧专用键，仅供 benchmark.config 读取，
            # 不参与 pydantic-settings，因此不算冲突。
            continue
        if key.upper() in _INTENTIONAL_OVERRIDES:
            continue
        actual = os.environ.get(key)
        if actual is not None and actual != val:
            out.append((key, _mask(key, actual), _mask(key, val)))
    return out
