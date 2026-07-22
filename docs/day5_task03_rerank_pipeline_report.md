# D5-03 Rerank Pipeline Integration Report

## 修改文件

- `backend/src/config.py`、`.env.example`：明确候选池和最终输出配置语义。
- `backend/src/rag/retrieval/pipeline.py`：接入 Rerank、失败回退、请求级计数和分阶段耗时。
- `backend/src/rag/runtime.py`：在唯一运行时装配入口构造或注入 Reranker。
- `backend/src/rag/service.py`：通用适配带 diagnostics 的 Retriever，并在 `RAGResponse` 中传播。
- `backend/src/agent/state.py`、`backend/src/agent/nodes.py`：把整体 retrieval diagnostics 写入请求状态；未加入检索阶段分支逻辑。
- `backend/src/rag/retrieval/reranker.py`：统一使用 `rerank_top_k` 配置。
- `backend/tests/test_retrieval_pipeline.py`：覆盖成功重排、禁用、降级、候选边界、分数和耗时。
- `backend/tests/test_hybrid_agent_graph.py`：覆盖 Rewrite → Retrieve/Fusion/Rerank → Context → Generate 及引用顺序。
- `backend/tests/test_retrieval_runtime.py`：覆盖运行时 Reranker 注入。
- `backend/tests/test_rag_service.py`：覆盖 diagnostics 与最终候选一起传播。
- `backend/tests/test_config.py`、`backend/tests/test_reranker.py`：同步配置契约。

## Pipeline 顺序

```text
Dense Top-N + BM25 Top-N
  -> RRF Fusion / Dense candidate selection
  -> retrieve_top_n candidate pool
  -> Reranker
  -> rerank_top_k final hits
  -> ContextBuilder
  -> Answer Generation
```

所有 Dense、BM25、Fusion 和 Reranker 分支都位于 `HybridRetrievalPipeline`。Agent 节点只通过通用 `execute_retrieval()` 获取最终 hits 和可选 diagnostics，然后把最终 hits 交给 ContextBuilder。

## 配置语义

```env
DENSE_TOP_N=20
BM25_TOP_N=20
RETRIEVE_TOP_N=20
RERANK_TOP_K=5
```

- `dense_top_n`、`bm25_top_n`：实际下推到底层 Retriever 的召回数；
- `retrieve_top_n`：Fusion 后进入 Cross-Encoder 的候选池上限；Dense-only 模式下同样限制候选池；
- `rerank_top_k`：最终交给 ContextBuilder 的结果上限；禁用或降级时也按该上限截取原候选顺序；
- Pipeline 校验底层召回数不得小于 `retrieve_top_n`，避免配置看似过召回而底层候选不足。

D5-03 将旧 `fusion_top_n` 正式升级为 `retrieve_top_n`，并将 D5-02 的 `reranker_top_n` 升级为 `rerank_top_k`。这是有意的公开配置契约调整，调用方、环境示例和测试已同步更新；旧环境变量 `FUSION_TOP_N`、`RERANKER_TOP_N` 仍作为兼容输入别名映射到同一个权威字段。

## Reranker 行为

- Hybrid：先完成 RRF，再把 Fusion 候选传给 Reranker；
- Dense-only：直接把有界 Dense 候选传给 Reranker；
- Disabled：不调用 Reranker，保留候选顺序；
- Empty：没有候选时不调用 Reranker；
- Failure：只捕获 `RerankerError` 契约内异常，回退到原候选顺序；程序错误继续抛出；
- Success：保留 metadata、`dense_score`、`bm25_score`、`fused_score`，只新增 `rerank_score`；
- Fallback：不伪造 `rerank_score`。

## 请求级 Diagnostics

每个 `RetrievalResult` 携带独立 `RetrievalDiagnostics`：

- `mode`
- `dense_count`
- `bm25_count`
- `fused_count`
- `rerank_input_count`
- `rerank_output_count`
- `reranker_enabled`
- `reranker_degraded`
- `degraded_reason`
- `degraded_sources`
- `dense_latency_ms`
- `bm25_latency_ms`
- `fusion_latency_ms`
- `rerank_latency_ms`
- `total_latency_ms`

降级原因只使用固定安全代码，例如：

- `reranker_request_failed`
- `reranker_response_invalid`
- `reranker_configuration_invalid`
- `reranker_input_invalid`

Provider 错误文本、API key、候选正文和异常堆栈不会进入 diagnostics。

## Service 与 LangGraph 适配

`execute_retrieval()` 使用结构化能力检测：

- 对 `HybridRetrievalPipeline` 调用 `retrieve_with_diagnostics()`；
- 对原有简单 Retriever 继续调用 `retrieve()`。

因此已有 Fake Retriever、基础 RAG Service 和 Agent 抽象保持兼容。`RAGResponse.retrieval_diagnostics` 与 `AgentState.retrieval_diagnostics` 都是可选的请求局部结果。

ContextBuilder 只接收最终候选。测试证明重排后的 `retrieved_documents`、`context_chunk_ids`、`context_sources` 和 `[S1]/[S2]` 编号顺序完全一致。

## 确定性案例

输入排名：

| 阶段 | 排名 |
|---|---|
| Dense | `a, b` |
| BM25 | `b, c` |
| RRF | `b, a, c` |

固定 Fake Reranker 分数：

| Chunk | Score |
|---|---:|
| `c` | 0.95 |
| `a` | 0.70 |
| `b` | 0.20 |

`rerank_top_k=2` 的最终结果为 `c, a`。对应自动化测试同时断言 RRF 候选输入顺序、最终顺序、原始分数保留和 diagnostics 计数。

## 测试结果

专项测试：

```bash
cd backend
uv run pytest tests/test_retrieval_pipeline.py \
  tests/test_retrieval_runtime.py tests/test_hybrid_agent_graph.py \
  tests/test_agent_graph.py tests/test_agent_rag_nodes.py \
  tests/test_agent_contracts.py \
  tests/test_rag_service.py tests/test_config.py tests/test_reranker.py -q
```

结果：`117 passed in 5.80s`

全量回归：

```bash
cd backend
uv run pytest -q
```

结果：`363 passed, 1 skipped in 38.46s`。跳过项仍为原有显式 opt-in 的外部 LLM Smoke；所有 Reranker/Pipeline 测试保持离线。

附加验证：冷启动导入检查和 `python -m compileall -q src tests` 均通过。

## 已知限制

- Pipeline 当前为同步执行，阶段耗时为本地 wall-clock duration；
- 降级只捕获公开 `RerankerError`，未知程序错误不会被静默吞掉；
- 未实现重试、熔断或异步并行 Dense/BM25；
- 未接入 Langfuse，本任务仅准备请求级诊断数据；
- 未实现 FastAPI、SSE 或 UI 展示；
- 真实 Provider Smoke 仍需显式凭证运行。
