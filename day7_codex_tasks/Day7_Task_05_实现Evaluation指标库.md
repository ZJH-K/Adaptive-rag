# Day 7 Task 05：实现 Evaluation 指标库

## 目标

实现独立、确定性、可单元测试的 RAG Evaluation 指标库，至少支持 Hit Rate@K、Recall@K、MRR 和关键词答案正确性，并为实验 Runner 提供稳定的单样本结果与聚合结果数据结构。

## 上下文

技术文档要求的核心检索指标：

- Hit Rate@K：Top-K 中是否至少命中一个相关 Chunk；
- Recall@K：相关 Chunk 被召回的比例；
- MRR：第一个相关 Chunk 排名的倒数；
- Average Latency：检索平均耗时；
- Rerank Gain：Rerank 前后相关 Chunk 排名变化。

第一版答案指标至少包括：

- 关键词覆盖率/答案正确性；
- 引用完整率；
- 无依据回答比例；
- LLM-as-a-Judge 可作为后续项，不是本任务 P0。

Day7 原始任务明确要求实现前三个检索指标和关键词答案正确性。

## 范围

### 必须实现的检索指标

1. `hit_rate_at_k(retrieved_ids, relevant_ids, k)`
2. `recall_at_k(retrieved_ids, relevant_ids, k)`
3. `reciprocal_rank(retrieved_ids, relevant_ids)`
4. 支持多个 K，例如 1、3、5、10。
5. 对整个数据集聚合：
   - Mean Hit Rate@K；
   - Mean Recall@K；
   - MRR；
   - 有效样本数、跳过样本数。

### 必须实现的答案指标

1. 关键词覆盖率：命中关键词数 / 期望关键词数；
2. 关键词全命中布尔值；
3. 中文和英文大小写/空白归一化；
4. 技术标识符保留 `_`、`-`、`.` 的可匹配性；
5. 可配置“全部关键词必须命中”或“至少命中阈值”。

### 建议实现的 P1 指标

1. `average_latency_ms`；
2. `rerank_gain`：相关 Chunk 首位排名或平均排名的变化；
3. 引用完整率：答案中的 `[Sx]` 与实际 Context Sources 的对应完整性；
4. 无依据回答比例：有答案但无可验证来源的比例。

### 数据结构

定义清晰的结果模型，例如：

- `RetrievalMetrics`；
- `AnswerMetrics`；
- `SampleEvaluationResult`；
- `AggregateEvaluationResult`。

模型应支持 JSON 序列化，方便 Task 06 生成 JSON/Markdown 报告。

### 边界行为必须定义

1. `k <= 0`；
2. retrieved 为空；
3. relevant 为空；
4. retrieved 中重复 Chunk ID；
5. relevant 中重复 Chunk ID；
6. 相关 Chunk 在 Top-K 外；
7. 答案为空；
8. expected keywords 为空；
9. 中文标点、大小写、Unicode 空白；
10. 同一 Chunk 被 Dense/BM25 重复召回后只计算一次排名。

### 不包含

- 不负责读取真实模型或执行检索；
- 不运行四组实验；
- 不接入 RAGAS；
- 不实现 LLM-as-a-Judge 作为 P0；
- 不把人工主观评分混入确定性指标。

## 约束

1. 指标必须是纯函数或无外部副作用模块，不能依赖 Chroma、LLM、网络或环境变量。
2. 排名定义从 1 开始，MRR 公式必须明确。
3. 对空 relevant 集不能静默给出误导性 0 或 1；应按统一策略标记 invalid/skipped，并在聚合中可见。
4. 重复 retrieved ID 应按第一次出现的排名去重，不能重复增加命中。
5. 关键词归一化规则要文档化，不能为了单个样本特殊处理。
6. 测试不得只验证 happy path，必须覆盖数值精度和边界。

## 验证方式

### 必须包含的测试

1. Hit Rate 命中/未命中；
2. Recall 多相关 Chunk、部分命中、全部命中；
3. MRR 第一名、第三名、未命中；
4. 重复 ID 不重复计分；
5. 多 K 聚合；
6. 空 retrieved；
7. 空 relevant 的显式策略；
8. 中文关键词覆盖；
9. `thread_id`、`BAAI/bge-reranker-v2-m3`、`similarity_search` 等技术标识符；
10. JSON 序列化结果字段稳定；
11. rerank gain（若实现）正/负/不变；
12. 引用完整率（若实现）严格使用 Context Sources。

### 建议命令

```bash
cd backend
uv run pytest -q tests/test_evaluation_metrics.py
uv run pytest -q
```

## 最终交付

1. `evaluation/metrics.py` 或等价模块；
2. 结果数据模型；
3. 指标单元测试；
4. `evaluation/METRICS.md`，包含公式、边界定义和聚合规则；
5. 一份完成报告，列出支持指标、未实现指标和测试结果。
