# Benchmark 评测报告模板

> 每次 Prompt / RAG / 模型变更后自动生成。

## 1. 概览

| 项 | 值 |
| --- | --- |
| run_tag | `{{run_tag}}` |
| 时间 | `{{time}}` |
| 样本总数 | `{{total}}` |
| 模型 | `{{model}}` |
| Prompt 版本 | `{{prompt_version}}` |

## 2. Coverage（覆盖度）

- 各意图占比：`{{coverage.per_category}}`
- 对抗性样本占比：`{{coverage.adversarial_ratio}}`（建议 ≥ 10%）

## 3. 检索质量（RAG）

| 指标 | 值 | 说明 |
| --- | --- | --- |
| Recall@5 | `{{recall_at_5}}` | 检索到相关文档 / 应召回总数 |
| MRR | `{{mrr}}` | 首个相关文档排名 |
| Chunk Size A/B | `{{chunk_ab}}` | 100/200/500 对比 |

> 注意：只提升召回率不够，需同时看忠实率与答案正确率。

## 4. Correctness

| 指标 | 值 |
| --- | --- |
| 专家抽检均值 | `{{correctness.human_mean}}` |
| LLM-as-a-Judge 均值 | `{{correctness.judge_mean}}` |
| 两者相关性 Pearson | `{{correctness.human_judge_correlation}}` |

> 相关性需 > 0.7，否则 LLM-as-a-Judge 不可信，需调 judge prompt。

## 5. 对抗性用例

- 前提错误识别率：`{{adversarial_pass_rate}}`
- 失败样例：`{{adversarial_failures}}`

## 6. 延迟与成本

| 指标 | 值 |
| --- | --- |
| P50 / P90 延迟(ms) | `{{latency.p50}} / {{latency.p90}}` |
| 总成本(USD) | `{{total_cost_usd}}` |

## 7. 回归对比

| run_tag | Recall@5 | Judge均值 | 结论 |
| --- | --- | --- | --- |
| `{{baseline_tag}}` | `{{baseline_recall}}` | `{{baseline_judge}}` | 基线 |
| `{{run_tag}}` | `{{recall_at_5}}` | `{{correctness.judge_mean}}` | `{{conclusion}}` |

## 8. 失败用例清单

`{{failure_list}}`
