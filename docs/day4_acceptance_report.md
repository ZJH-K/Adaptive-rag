# Day 4 Hybrid Retrieval Acceptance Report

## Overall Status

**PASS**

Day 4 的实现、专项回归、离线对比实验和全量回归均达到任务验收门槛。该结论只覆盖确定性离线行为与仓库内集成，不代表真实 Embedding 服务上的线上检索质量。

## Scope

本次验收覆盖 D4-01 至 D4-06 已实现的契约修复、中文/技术词 tokenizer、BM25 索引与检索器、RRF、Dense/Hybrid 检索流水线、Agent/LangGraph 接入、来源映射，以及 D4-07 的小型离线对比实验。

未实现 BGE Reranker、Langfuse、API/UI、Docker、LLM-as-a-Judge 或 Day 7 完整评估框架。

## Implementation Summary

- 使用 `JiebaTokenizer` 统一 BM25 建库与查询分词，保留 `thread_id`、`similarity_search`、`BAAI/bge-reranker-v2-m3` 等技术词。
- `BM25Index` 保持 corpus 位置到 `Chunk` 的稳定映射；`BM25Retriever` 返回统一 `SearchHit`，并保留 metadata 与原始 BM25 分数。
- RRF 仅使用排名计算融合分数，保留 Dense/BM25 原始分数，并以最佳来源排名和 `chunk_id` 提供确定性 tie-break。
- `HybridRetrievalPipeline` 支持 Dense-only/Hybrid、单路为空、已知单路失败降级、双路为空和候选数量配置；编程错误与数据契约错误不会被静默吞掉。
- Agent 检索节点只依赖检索流水线接口，使用 `rewritten_query`；Direct 分支不会触发检索。
- `ContextBuilder` 生成的 actual sources、citation ID 与实际进入上下文的 Chunk 保持一一对应。
- 新增 8 个 Chunk、5 个查询的离线夹具与结构化对比脚本；Dense 排名是显式固定的 fake 输入，BM25 与 RRF 使用项目真实实现。

## Requirement Check

| Requirement | Evidence | Result |
| --- | --- | --- |
| tokenizer 覆盖中英混合技术词 | `test_tokenizer.py` | PASS |
| BM25 索引位置映射稳定 | `test_bm25_index.py` | PASS |
| BM25 返回统一 SearchHit | `test_bm25_retriever.py` | PASS |
| RRF 公式、分数保留与 tie-break | `test_rrf_fusion.py` | PASS |
| Dense-only/Hybrid 开关 | `test_retrieval_pipeline.py` | PASS |
| 单路为空或已知失败可降级 | `test_retrieval_pipeline.py` | PASS |
| 两路都为空稳定返回空结果 | `test_retrieval_pipeline.py` | PASS |
| rewritten_query 被实际检索使用 | `test_agent_rag_nodes.py`, `test_hybrid_agent_graph.py` | PASS |
| Direct 分支零检索 | `test_agent_router.py`, `test_hybrid_agent_graph.py` | PASS |
| actual sources/citation 精确映射 | `test_context_builder.py`, `test_agent_rag_nodes.py` | PASS |
| Router/Rewrite 结构化输出回归 | `test_agent_contracts.py`, `test_agent_router.py`, `test_agent_rewrite.py` | PASS |
| 至少 5 个查询、至少 3 个 Hybrid 提升案例 | 5 个查询中 4 个提升，Hit@3 从 2/5 到 5/5 | PASS |
| Day 1–Day 3 无回归 | 全量 309 passed，1 个外部 smoke 默认 skipped | PASS |

## Test Results

### Day 4 专项测试

命令：

```bash
cd backend
uv run pytest -q tests/test_hybrid_quality_cases.py tests/test_tokenizer.py tests/test_bm25_index.py tests/test_bm25_retriever.py tests/test_rrf_fusion.py tests/test_retrieval_pipeline.py tests/test_hybrid_agent_graph.py tests/test_context_builder.py tests/test_agent_contracts.py tests/test_agent_graph.py tests/test_agent_rag_nodes.py tests/test_agent_router.py tests/test_agent_rewrite.py tests/test_llm_client.py tests/test_config.py tests/test_ingestion.py tests/test_chroma_vectorstore.py
```

结果：`212 passed in 36.62s`。

### 相关模块覆盖率

命令：

```bash
cd backend
uv run pytest -q tests/test_tokenizer.py tests/test_bm25_index.py tests/test_bm25_retriever.py tests/test_rrf_fusion.py tests/test_retrieval_pipeline.py tests/test_hybrid_agent_graph.py tests/test_context_builder.py tests/test_agent_rag_nodes.py tests/test_hybrid_quality_cases.py --cov=src.rag.retrieval --cov=src.agent.nodes --cov-report=term-missing
```

结果：`105 passed in 27.94s`；所选模块合计语句覆盖率 `96%`。其中 tokenizer、BM25 index、BM25 retriever 为 `100%`，fusion 与 pipeline 为 `98%`，Agent nodes 为 `88%`。

### 全量测试

命令：

```bash
cd backend
uv run pytest -q
```

结果：`309 passed, 1 skipped in 53.22s`。唯一跳过项为显式 opt-in 的真实 DeepSeek 结构化输出 smoke test；默认离线测试没有发起外部 API 请求。

## Dense vs Hybrid Cases

复现命令：

```bash
cd backend
uv run python scripts/compare_dense_hybrid.py
```

实验使用提交到仓库的固定 Chunk 与 fake Dense 排名；BM25 排名和最终 RRF 排名由生产代码现场计算。Top-K 为 3。结构化 JSON 输出包含 query、relevant IDs、三路排名、首次命中排名、排名增益和原因。

| Query | Relevant | Dense Top-3 | BM25 Top-3 | Hybrid Top-3 | Relevant rank | Explanation |
| --- | --- | --- | --- | --- | --- | --- |
| `checkpoint 配置键 thread_id` | `checkpoint-thread` | semantic-state, rrf-fusion, generic-ranking | checkpoint-thread | checkpoint-thread, semantic-state, rrf-fusion | 5 → 1 | BM25 保留带下划线配置键，纠正语义干扰。 |
| `Chroma similarity_search 如何调用` | `chroma-similarity` | semantic-vector, bge-embedding, generic-ranking | chroma-similarity | chroma-similarity, semantic-vector, bge-embedding | 5 → 1 | 完整函数名提供精确词项命中。 |
| `BAAI/bge-reranker-v2-m3 重排模型` | `bge-reranker` | bge-embedding, generic-ranking, semantic-vector | bge-reranker, bge-embedding, generic-ranking | bge-embedding, generic-ranking, bge-reranker | 5 → 3 | BM25 区分相近模型名，使目标进入 Top-3；未夸大为第 1 名。 |
| `RRF 融合公式` | `rrf-fusion` | generic-ranking, rrf-fusion, semantic-vector | rrf-fusion | rrf-fusion, generic-ranking, semantic-vector | 2 → 1 | 缩写精确命中进一步提升排名。 |
| `LangGraph 如何持久化图状态` | `checkpoint-thread` | checkpoint-thread, semantic-state, rrf-fusion | checkpoint-thread, semantic-state | checkpoint-thread, semantic-state, rrf-fusion | 1 → 1 | Dense 已排首，Hybrid 保持结果，作为无差异对照。 |

汇总：Dense Hit@3 = `2/5`，Hybrid Hit@3 = `5/5`；4 个查询排名提升，1 个无差异，无退化案例。该小样本证明确定性融合行为与关键词补偿能力，不是对真实 embedding 模型的统计质量结论。

## Architecture Check

- 检索器继续返回统一 `SearchHit`，Agent 不感知 Dense、BM25 或 RRF 的实现细节。
- tokenizer、BM25 index、BM25 retriever、fusion 和 orchestration 职责分离。
- BM25 生命周期由 ingestion 完成后基于向量库中的 Chunk 重建，不进入 parser/chunker/embedding 的职责边界。
- ContextBuilder 决定实际进入 prompt 的 Chunk，并同时产生对齐的 citation/source 映射。
- 降级只捕获已知检索服务错误；无效数据与程序错误继续显式抛出，便于诊断。

## Known Issues

- 对比实验的 Dense 排名是确定性 fake 输入，尚未验证真实 `BAAI/bge-m3` 或其他远程 embedding 模型上的提升幅度。
- 真实 DeepSeek Router/Rewrite smoke test 未执行；需显式设置 `RUN_LLM_SMOKE=1` 且配置合法 API key。
- 数据集仅含 8 个 Chunk、5 个查询，适用于 Day 4 行为验收，不可替代 Day 7 的 Recall@K/MRR 与更大样本评估。
- 当前 BM25 索引为进程内全量重建，尚未覆盖大规模增量更新、并发写入与持久化恢复。
- Day 5 的 reranker 与 Langfuse 尚未实现，这符合本任务边界。

## Impact on Day 5

- Reranker 应消费 RRF 输出的统一 `SearchHit` 列表，位于融合之后、ContextBuilder 之前；应保留 `dense_score`、`bm25_score`、`rrf_score`，并只新增 `rerank_score`。
- Reranker 失败时可回退到当前 RRF 顺序，不能改变 Agent 与 ContextBuilder 的输入契约。
- Langfuse 可围绕 Dense、BM25、RRF、Reranker 和 LLM 节点增加 span，但不应让观测逻辑进入各算法实现。
- Day 7 评估可复用本脚本的结构化结果形态，但应另建更大、包含真实 Dense 输出的数据集和完整指标层。

## Final Recommendation

接受 Day 4，进入 Day 5。进入真实环境质量结论前，应单独执行外部 Embedding/LLM smoke test，并在 Day 7 使用真实 Dense 输出和更大评估集复核 Hybrid 收益。
