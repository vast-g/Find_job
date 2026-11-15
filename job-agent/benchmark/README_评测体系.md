# 求职 Agent 评测体系 · 使用说明

> 项目：国企/央企求职 AI Agent（FastAPI + LangGraph ReAct + RAG + 长短记忆）
> 目标：把简历里「LLM-as-Judge + Agent Trace 自动化评测 / Bad Case 回归优化」做成**真实可信、可一键运行**的东西。

---

## 一、先说结论：原评测为什么不可信

改造前项目里**已经有一套 `benchmark/` 脚手架**，但有几个硬伤，导致跑出来的数字不能用来支撑简历。

| # | 问题 | 后果 |
|---|------|------|
| 1 | **裁判与被测是同一个模型实例**（都走 `app.llm.factory.get_chat_model()`） | 自己批改自己的作业，"正确率"没有说服力 |
| 2 | JSON 解析失败 → 返回 `correctness: 0.0` | 把"判不了"当成"答错了"，系统性拉低分数且不可见 |
| 3 | 判官返回的 `faithfulness` / `context_utilization` **被丢弃**（只取了 `correctness`） | 两个指标形同虚设 |
| 4 | 把 `retrieved_docs`（**doc_id 列表**）当"上下文文本"传给判官 | 判官看到的是一串 ID，忠实度判定完全无效 |
| 5 | `golden_tools` 字段存在但**从未被使用** | 没有 Tool Accuracy |
| 6 | 没有意图准确率 | 没有 Route Accuracy |
| 7 | **FAISS 索引只从 `data/docs/` 建（2 个片段）**，知识库主体 `data/knowledge.jsonl`（16 篇）**从未入库** | 检索几乎为空 |
| 8 | 数据集的 `ground_truth_docs` 写的是 `doc_alg_job_001` 这类**索引里不存在**的 ID | **Recall@5 与 MRR 恒为 0** |
| 9 | 数据集只有 **6 条** | 无法支撑任何统计结论 |
| 10 | `metrics.correctness` 的 Pearson 按位置配对，但两个列表分别过滤过 | 人工/裁判相关性算错位 |
| 11 | `per_category` 恒为 `{}` | 报告里没有分类拆解 |

另外还有三个**运行时阻塞**：

- **Redis 是硬依赖**（`AgentPipeline.__init__` 直接 `RedisMessageStore(get_redis())`），
  而本机 **Redis 根本没装**（6379 不通）→ 评测连启动都启动不了；
- **`get_user_applications` 工具注册了，却不在任何意图的白名单里** → Agent 永远调不到它，
  而数据集的对抗用例恰恰期望这个工具；
- `ObservabilityCallbackHandler.on_tool_end` 复用请求主 session 写库，
  在 ORM flush 过程中触发会抛 `InvalidRequestError('Session is already flushing')`
  → **工具痕迹根本写不进 `agent_trace`**。

---

## 二、改了什么

### 运行阻塞（3 项）

| 改动 | 文件 | 说明 |
|------|------|------|
| 新增进程内记忆后端 | `app/memory/memory_store.py`、`app/memory/factory.py` | `MEMORY_BACKEND=memory` 时完全不依赖 Redis；评测每条用例独立 session，天然隔离 |
| 补全工具白名单 | `app/core/pipeline.py` | `get_user_applications` 补入 `qa` 意图（由评测集的对抗用例暴露） |
| Trace 落库重构 | `app/observability/callback.py` | 内存缓冲 + **独立 session** 收尾落库；回调全改**同步方法** |
| 索引重建 | `app/rag/indexer.py` | 新增 `build_all`：知识库 16 篇 + 文档 2 篇，索引从 **2 个片段 → 18 个片段** |

> 关于"回调改同步"：实测把 `on_tool_start` 写成 `async def` 会导致它
> **根本不被调用**（LangChain 的回调分派对 `on_*` / `aon_*` 走不同路径），
> 现象是工具名恒为空、`tool_start` 行完全缺失。缓冲本身不需要 await，
> 同步实现最可靠；唯一的异步落库由 `aflush()` 显式触发。

### 评测体系（重写）

| 文件 | 作用 |
|------|------|
| `benchmark/judge.py` | **独立裁判**（百炼 glm-5.3）+ JSON Schema 约束 + `unknown` 一等公民 + 自一致性投票 + 磁盘缓存 |
| `benchmark/metrics.py` | 五项核心指标 + 检索质量 + 运行健康度 + 裁判可靠性 |
| `benchmark/evaluate.py` | 并发执行 + 单条超时 + 会话隔离 + 结果落盘 |
| `benchmark/report.py` | Markdown 报告（含基线对比、分类拆解、口径说明） |
| `benchmark/badcase.py` | 8 类归因挖掘 + 回归集去重累积 |
| `benchmark/regression.py` | 基线管理与回归门禁 |
| `benchmark/cli.py` | 统一命令行入口 |
| `benchmark/config.py` | 评测专用配置（与被测系统配置分离） |

### 数据集

| 文件 | 内容 |
|------|------|
| `benchmark/dataset/testset.jsonl` | **75 条**带标签样本（20 岗位推荐 / 15 简历优化 / 25 面试问答 / 15 对抗性），覆盖全部 18 篇知识库文档 |
| `benchmark/dataset/regression.jsonl` | 运行 `mine` 后自动累积的回归集 |

### 工具

| 文件 | 作用 |
|------|------|
| `tools/validate_dataset.py` | 数据集校验（枚举合法性 + **工具是否落在意图白名单内** + doc_id 真实性） |
| `tools/selftest_pipeline.py` | **离线**管线自测（不调模型，秒级） |
| `tools/inspect_trace.py` | 查看最近 N 次请求的 Agent Trace，人工核查埋点 |

---

## 三、怎么跑

### 完整流程：两步

**第一步 —— 构建知识库**（新增/更新资料后必做）

双击 `rebuild_kb.bat`：

```
[1] Quick rebuild   仅项目内资料               约 1 分钟
[2] Full rebuild    含外部资料合集             约 30-50 分钟
[3] Show current index content
[0] Cancel
```

**第二步 —— 跑评测**

双击 `run_eval.bat`：

```
[ SETUP ]
[1] 环境预检          [2] 裁判自检          [3] 离线管线自测
[4] 数据集校验        [C] 重建知识库
[ RUN ]
[5] 试跑 3 条（不算裁判）   [6] 试跑 10 条（含裁判）   [7] 全量 75 条
[ RESULTS ]
[8] 重新生成报告   [9] 挖掘 Bad Case   [A] 设为基线   [B] 回归门禁
```

> ⚠️ 这两个 .bat **必须保持纯 ASCII 内容**，原因见第十节。

### 命令行

```bash
# 知识库
python -m app.rag.indexer build_all              # 全量（含外部资料）
python -m app.rag.indexer build_all --no-extra   # 仅项目内资料
python tools\verify_index.py                     # 验证索引可用性与加载耗时
python tools\compare_bm25.py                     # BM25 中文分词 A/B 对比

# 评测
python -m benchmark.cli check                 # 环境预检（几秒）
python -m benchmark.cli judge-test            # 裁判自检（2 次 API 调用）
python -m benchmark.cli run --limit 3 --no-judge   # 先验证 Agent 链路，不算裁判
python -m benchmark.cli run --limit 10        # 小样本带裁判
python -m benchmark.cli run --all             # 全量 75 条
python -m benchmark.cli mine                  # 挖 Bad Case + 更新回归集
python -m benchmark.cli baseline              # 设为基线
python -m benchmark.cli gate                  # 回归门禁
```

### 产物位置

```
benchmark/reports/eval_report_*.md      # 人看的报告
benchmark/reports/eval_results_*.json   # 机器读的结果（含逐条明细）
benchmark/reports/latest_*.json         # 供门禁比较
benchmark/reports/judge_cache.json      # 裁判缓存（重跑零成本）
benchmark/bad_cases/badcases_*.jsonl    # 归因后的 Bad Case
benchmark/dataset/regression.jsonl      # 回归集
```

---

## 四、五项指标口径

| 指标 | 怎么算 | 为什么这么算 |
|------|--------|-------------|
| **Route Accuracy（意图路由）** | 预测意图 == 期望意图 | 意图是三分类输出，有精确解，用 LLM 打分只会引入噪声 |
| **Tool Accuracy** | 期望工具集 vs 实调工具集的 P/R/F1 + 完全匹配率 | 集合比较，同样有精确解；重复调用同一工具不额外扣分 |
| **Task Completion Rate** | 按每条样本的 `success_criteria` 判 pass/fail | 不同类别标准不同（对抗样本要求"纠正错误前提"而非"答得好"） |
| **Faithfulness** | 回答切原子陈述 → 逐条判断能否被**检索上下文正文**蕴含 | 判官拿的是正文而非 doc_id，这才是有意义的蕴含判定 |
| **Context Recall** | 标准答案要点 → 逐条判断能否在上下文中找到支撑 | 无参考答案要点的样本**不参与**该项，不编分数 |

外加：**Recall@K / Hit@K**（检索质量）、**对抗性完成率**、**延迟/token/成本**、**裁判可靠性**。

### 三个关键设计

1. **裁判与被测模型分离**：被测 `deepseek-v4.1-flash`，裁判 `glm-5.3`。
2. **`unknown` 是一等公民**：判不了就如实记录并单独统计，绝不折算成 0 分。
3. **doc_id 按前缀匹配**：索引里是 `doc_interview_flow#0`（含分块序号），
   数据集只写到源文档 `doc_interview_flow`，比对时取 `#` 前部分 ——
   否则"同一文档的其它分块"会被误判为未召回。

---

## 五、成本预估

实测单条用例：
- 被测模型（deepseek-v4.1-flash）：约 **$0.027/条**（含 ReAct 多轮）
- 裁判（glm-5.3）：约 **22 次判定/条**

**75 条全量预估：被测 $2 左右 + 裁判若干**。
建议先 `run --limit 10` 看实际账单，再决定是否 `--all`。
**裁判结果有磁盘缓存**（`judge_cache.json`），同一输入重复评测不再花钱。

---

## 六、已经验证过的（真实运行，非纸面）

| 验证项 | 结果 |
|--------|------|
| 环境预检 | 全部 OK（记忆后端 / 裁判 key / 数据集 / FAISS / 依赖 / MySQL / Ollama） |
| 离线管线自测 | **全部通过**（工具评分、doc 前缀匹配、指标汇总、报告、Bad Case、回归集去重） |
| 数据集校验 | **全部通过**（75 条，工具白名单 0 违规，doc_id 全覆盖） |
| Agent 链路真机跑通 | ✅ 3 条用例，意图路由 100%，延迟约 20s/条 |
| **Agent Trace 埋点** | ✅ 单请求 16 行：`intent` / `llm` / `tool_start`(含工具名+参数) / `tool`(含检索正文) |
| 完整指标 + 真实裁判 | ✅ 2 条用例：Route 100% / Tool F1 1.0 / Task Completion 100% / Faithfulness 70.8% / Context Recall 62.5%，裁判一致率 0.98 |
| 全量索引重建 | ✅ 430 篇文档 → **14059 片段**，chunk=400，索引 137 MB |
| 索引加载性能 | ✅ 稠密 FAISS + BM25 共 **2.4 秒**；单次检索 **45-53 ms** |
| BM25 磁盘缓存 | ✅ 首次构建 8.8 秒 → 二次加载 **0.3 秒**（31 MB 缓存，语料变更自动失效） |
| 断点续跑 | ✅ 实测中断后重跑，从 `done=5000` 继续而非重头再来 |

---

## 七、评测过程中发现的真实缺陷（可直接写进简历）

这套评测跑起来后，**立刻发现了几个此前不知道的问题** —— 这正是"评测体系"的价值。
按严重程度排序：

### 1. `FAISS 索引只建了 2 个片段`（已修复）

知识库主体 `data/knowledge.jsonl`（16 篇）**从未进入索引**，索引只从 `data/docs/`
的 2 个文件建。同时评测集里的 `ground_truth_docs` 写的还是**索引中不存在的 ID**，
导致 **Recall@5 与 MRR 恒为 0** —— 检索质量指标全部失效。
修复：新增 `build_all` 合并建索引，并接入外部资料目录。

### 2. `BM25 对中文完全失效，且是在"灌垃圾"`（已修复）

langchain `BM25Retriever` 的默认预处理是按空格切分：

```python
def default_preprocessing_func(text): return text.split()
```

中文没有空格，于是**每个 400 字片段被切成 1 个 token**，查询同理。A/B 实测：

| 问题 | 默认分词 top10 | 中文分词 top10 |
|---|---|---|
| 国企面试从网申到签约有哪些环节 | 真题汇编卷 #18~21（无关） | `doc_interview_flow` ✅ |
| 无领导小组讨论注意什么 | 真题汇编卷 #18~21（**同一批**） | `doc_group_interview` ✅ |
| 行测和申论分别考什么 | 真题汇编卷 #18~21（**又一样**） | `doc_exam_overview`、`doc_shenlun` ✅ |
| 谈薪注意什么 | 真题汇编卷 #18~21（**还是它**） | `doc_salary_negotiation` ✅ |

**四个完全不同的问题返回同一批文档** —— 说明 BM25 实际在返回零分噪声。
而 RRF 融合是**按排名**合并两路结果的，这些垃圾文档带着排名进入融合，
**会把真正正确的稠密检索结果挤下去**。所以它不是"没贡献"，是**在破坏召回**。

修复：传入 jieba 分词器（`app/rag/tokenizer.py`），并加**磁盘缓存**
（首次 8.8 秒构建 → 之后 0.3 秒加载），避免启动变慢。

### 3. `参数名写错被静默忽略`（踩坑记录，值得警惕）

第一次修复时写的是 `preprocessor=tokenize_zh`，而这个版本的字段名是
**`preprocess_func`**。传错的参数进了 `**kwargs`，被 pydantic **静默丢弃** ——
不报错、不警告、没有任何提示，代码"看起来修好了"。

**发现方式**：BM25 构建只花了 0.2 秒，而 jieba 实测全量分词需要约 10 秒。
这个数字对不上才揪出来。

**加固**：构建后校验 `retriever.preprocess_func is tokenize_zh`，不符合直接抛异常。
以后再遇到 langchain 改字段名会**立刻报错**，而不是悄悄退化。

### 4. `get_user_applications` 在任何意图下都不可达（已修复）

工具已注册，但不在任何意图的白名单里 → Agent 永远调不到它，
而数据集的对抗用例恰恰期望这个工具。

### 5. `工具痕迹写不进 agent_trace`（已修复）

回调复用请求主 session 写库，而回调是在 ORM flush 过程中触发的，
必然抛 `InvalidRequestError('Session is already flushing')`，
**工具调用痕迹每次都被吞掉**。

### 6. `Agent 有时不调工具、反问用户要 user_id`（未修复，待观察）

同一个问题两次运行，一次正常调用 `get_user_resume` + `search_jobs`，
一次直接回"请提供您的用户 ID"。→ 指向 `get_user_resume` 的参数设计
（工具需要 user_id，但模型无从得知，只能反问）。

> 以上**全部由评测首次运行时自动暴露**，不是人工翻代码找到的 ——
> 这就是"基于 Agent Trace 的自动化评测 + Bad Case 归因"的实际产出。

---

## 八、检索链路优化（本轮改动）

### 参数调整

| 配置 | 原值 | 新值 | 理由 |
|---|---|---|---|
| `RAG_TOP_K` | 5 | **15** | 它是**检索漏斗深度**而非"给 LLM 几条上下文"：稠密/稀疏各取 `top_k×2`、RRF 融合后保留 `top_k`，最终给 LLM 的始终是 rerank 的 5 条。语料 18 片段时 5 够用（几乎全捞），2.7 万片段时 5 只覆盖 **0.036%** |
| `RAG_CHUNK_SIZE` | 200 | **400** | 资料 PDF 平均 1.5 万字，200 字一块会切出大量细碎片段；400 让语义更完整，片段数约减半 |

> 顺带修复：`RAG_CHUNK_SIZE` 原本是**死配置** —— 索引 CLI 把默认值硬编码成 200，
> 改 `.env` 完全不生效。现在改为「命令行 > .env > 代码默认」。

### 工程加固（都是被真实故障逼出来的）

| 问题 | 修法 |
|---|---|
| 构建 20 分钟的任务因一次瞬时连接失败全废 | **单批重试 + 指数退避**（最多 8 次） |
| Ollama 内部 runner 换端口导致连不上，盲目重试无效 | **重试前先探测 Ollama 健康**（最多等 60 秒） |
| 中断后要从头再来 | **断点续跑**（每 500 片段存盘 + 语料指纹校验） |
| 模型被卸载重载 → 分配新内部端口 → 连接被拒 | **`EMBEDDING_KEEP_ALIVE=1800`** 让模型常驻 |
| 解析阶段 5 分钟完全静默 | 每 50 个文件打印进度 + 汇总空内容/失败数 |
| pypdf 的损坏对象警告淹没进度 | 日志级别降到 ERROR |

**关于断点续跑的语料指纹**：指纹由「分块大小 + 嵌入模型 + 全部片段内容」哈希而成。
改了其中任何一项，旧断点自动失效 —— 避免"续跑到了与当前语料不匹配的半成品索引上"
这种最难排查的隐蔽错误。

---

## 九、口径与前提（对外引用时必须说明）

1. **标签是 AI 生成的草稿**：`testset.jsonl` 全部 `reviewed: false`。
   `expected.关键点` 基于 `data/knowledge.jsonl` 真实正文撰写，但**尚未人工复核**。
2. **评测隔离**：每条用例独立 `session_id` + 进程内记忆后端，
   用例之间不共享短期记忆 —— 评的是"单题能力"。
3. **知识库规模随资料来源变化，历史指标不可直接比较**：
   - 初始：2 片段（知识库主体未入索引）
   - 中间：18 片段（知识库 + 项目内文档，chunk=200/400）
   - 当前：**14059 片段**（+ 外部资料合集 430 篇，chunk=400）
   每次语料或分块变化后，`Recall@K` / `Context Recall` / `Context Relevance`
   都会整体位移，**不要跨版本对比**。
4. **BM25 中文分词修复前后也不可比**：修复前 BM25 在往 RRF 里注入噪声，
   修复后稀疏检索才真正参与融合。这是行为变更，不是参数微调。
5. **评测条件**：检索参数的对照实验建议用 `--no-judge` 跑，
   只比较 `Recall@K`（不花裁判费用）。
6. **LLM 有随机性**：`LLM_TEMPERATURE=0.2`，同一问题重跑结果可能不同。
   要看趋势不要看单次快照。

---

## 十、修改过的既有文件（原文件已备份）

备份目录：`C:\Users\Lenovo\Desktop\Find_job\job-agent_backup_<时间戳>`

| 文件 | 改动 |
|------|------|
| `app/config.py` | 新增 `memory_backend`、`embedding_keep_alive`、`extra_docs_dirs`、`bm25_chinese_tokenizer` |
| `app/core/pipeline.py` | 用记忆工厂替代硬编码 Redis；补 `get_user_applications` 白名单；trace 收尾落库；step 序号衔接 |
| `app/observability/callback.py` | 重写：缓冲 + 独立 session + 同步回调 + 记录工具名与参数 |
| `app/rag/indexer.py` | 新增 `build_all`（递归 + 外部目录）；分批 + 重试 + 健康探测 + **断点续跑**；解析进度；修复 `RAG_CHUNK_SIZE` 死配置 |
| `app/rag/embeddings.py` | 新增 `keep_alive`，避免长任务中途模型被卸载 |
| `app/rag/hybrid_retriever.py` | **修复 BM25 中文分词**；新增 BM25 磁盘缓存与语料指纹；加载日志 |
| `app/rag/tokenizer.py` | **新增**：中文分词器（BM25 与 rerank 共用） |
| `app/memory/memory_store.py`、`app/memory/factory.py` | **新增**：进程内记忆后端，解除 Redis 硬依赖 |
| `benchmark/judge.py` | 重写 |
| `benchmark/metrics.py` | 重写 |
| `benchmark/evaluate.py` | 重写（`run_evaluation` 签名保留，API 路由不受影响） |
| `benchmark/badcase.py`、`benchmark/report.py`、`benchmark/cli.py`、`benchmark/config.py` | **新增** |
| `benchmark/regression.py` | 重写为门禁 |
| `benchmark/dataset/testset.jsonl` | **新增** 75 条带标签样本 |
| `data/faiss/*` | 索引重建（2 片段 → **14059 片段**） |

`benchmark/dataset/sample.jsonl` **保留未删**（原 6 条样例）。

### 一键脚本

| 文件 | 用途 |
|---|---|
| `run_eval.bat` | 评测中心（预检 / 自检 / 试跑 / 全量 / 报告 / Bad Case / 门禁） |
| `rebuild_kb.bat` | 重建知识库（快速 / 全量 / 查看索引） |

> ⚠️ **这两个 .bat 必须保持纯 ASCII 内容**。Windows cmd 用**控制台代码页**解析
> 批处理文件，而代码页因环境而异（936/GBK 或 65001/UTF-8）。文件里只要有中文，
> 在另一种代码页下就会被拆成乱码，`echo` 被吃掉，剩下的字全变成"命令"并报
> `不是内部或外部命令`。中文输出交给 Python（它会自动适配控制台编码）。
