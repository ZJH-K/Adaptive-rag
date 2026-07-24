# Evaluation 指标定义

`evaluation/metrics.py` 是无网络、无环境变量、无 Chroma/LLM 依赖的纯计算模块。排名从 1 开始；输入的重复 Chunk ID 按第一次出现的位置去重。

## 检索指标

设去重后的 Top-K 检索集合为 `R_K`，去重后的人工相关集合为 `G`：

- `Hit Rate@K = 1`，当且仅当 `R_K ∩ G` 非空，否则为 `0`。
- `Recall@K = |R_K ∩ G| / |G|`。
- `Reciprocal Rank = 1 / rank_first_relevant`；没有命中时为 `0`。
- 数据集 `MRR` 是所有有效样本 Reciprocal Rank 的算术平均。

`k` 必须是正整数。空 retrieved 是有效输入，对非空 relevant 产生 0 分。空 relevant 没有合法分母：低层标量函数抛出 `UndefinedMetricError`，`evaluate_retrieval` 则返回 `valid=false` 和原因，聚合时不纳入均值但计入 `skipped_sample_count`。聚合采用 macro average，每个有效问题权重相同。

默认同时计算 K=`1,3,5,10`。Runner 可以传入其他正整数序列；聚合要求每个有效样本都包含所请求的 K。

## 答案关键词指标

关键词覆盖率为“命中的唯一期望关键词数 / 唯一期望关键词总数”。同一关键词在答案中出现多次只计一次。`all_keywords_matched` 表示全命中；`passed` 支持两种策略：

- `require_all=true`：覆盖率必须为 1；
- `require_all=false`：覆盖率必须达到 `minimum_coverage`，阈值范围为 `[0,1]`。

答案和关键词统一执行 Unicode NFKC、Unicode `casefold`、连续空白折叠。除 `_`、`-`、`.` 外的 Unicode 标点被转换为词边界；包含中日韩统一表意文字的关键词还会忽略这些词边界，使“查询，改写”能够匹配“查询改写”。英文词边界保持有效，同时保留 `thread_id`、`similarity_search`、`BAAI/bge-reranker-v2-m3` 等技术标识符的可匹配部分。空答案是有效输入并得到 0 覆盖率；空 expected keywords 被显式标记为 skipped，标量 `keyword_coverage` 对此抛出 `UndefinedMetricError`。

## P1 指标

- `average_latency_ms`：非负、有限延迟值的算术平均；空集合未定义。
- `rerank_gain`：`重排前首个相关结果排名 - 重排后首个相关结果排名`。正值表示改善，负值表示退化，0 表示不变。两侧任一排名没有相关结果时未定义。

引用完整率与无依据回答比例尚未实现。它们需要 Task 06 Runner 明确传入最终 Context Sources 和可验证来源，避免从答案文本或检索候选中猜测依据。

## 结果模型

- `RetrievalMetrics`：单样本多 K 检索指标及有效状态。
- `AnswerMetrics`：覆盖率、全命中、阈值判定和命中/缺失关键词。
- `SampleEvaluationResult`：单样本检索、答案、延迟和可选 rerank gain。
- `AggregateEvaluationResult`：macro averages、有效/跳过数量及可选 P1 均值。

模型均为 Pydantic 模型，可用 `model_dump(mode="json")` 或 `model_dump_json()` 生成稳定的报告输入。
