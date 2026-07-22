# D6-01 检索失败类型化与单路降级验收记录

## 实现范围

- 新增稳定、可脱敏的检索异常层次，公开 `code`、`path`、`recoverable`、`safe_message`。
- Dense 适配器将 Embedding 请求故障和 Vector Store 服务故障转换为 Dense 路径可恢复异常。
- BM25 Retriever 将索引未构建、索引陈旧、分词 I/O/Unicode 故障和索引查询 I/O/Unicode 故障转换为 BM25 路径可恢复异常。
- Chroma 查询将明确的 Chroma 服务故障和 HTTP transport 故障转换为 Vector Store 可恢复异常。
- Hybrid Pipeline 仅捕获类型化的 `RetrievalPathUnavailableError`，单路失败使用另一条路径，双路失败抛出 `RetrievalUnavailableError(code="retrieval_unavailable")`。
- Agent retrieve 节点把总体检索失败映射为 `WorkflowFailure` fatal 状态，停止生成并提供稳定错误码，供后续 SSE 层消费。
- diagnostics 增加实际模式、请求模式、降级路径和安全错误码、RRF/Rerank 是否进入、各路径候选数和最终结果数。
- 保留 Reranker 已知失败回退到候选顺序的原有契约。

## 异常与判定

| 类型 | code 示例 | recoverable | 行为 |
|---|---|---:|---|
| `DenseRetrievalUnavailableError` | `embedding_request_failed` | true | Hybrid 中降级到 BM25 |
| `BM25RetrievalUnavailableError` | `bm25_index_stale` | true | Hybrid 中降级到 Dense |
| `VectorStoreUnavailableError` | `vector_store_unavailable` | true | Dense 适配器转换为 Dense 路径失败 |
| `RetrievalUnavailableError` | `retrieval_unavailable` | true | 当前请求 fatal；工作流停止生成，可稍后重试 |
| `RetrievalContractError` | `retrieval_contract_invalid` | false | 不参与降级，向调用方传播 |

`EmbeddingResponseError`、`VectorStoreResponseError`、RRF metadata 冲突、Pydantic/SearchHit 校验错误、断言错误以及未知 `RuntimeError` 均不会被 Pipeline 捕获或伪装成降级。

## 场景行为

| 场景 | 实际行为 |
|---|---|
| Dense 成功，BM25 可恢复失败 | 返回 Dense 结果；`mode=dense`；记录 BM25 安全错误码 |
| BM25 成功，Dense/Embedding/Chroma 可恢复失败 | 返回 BM25 结果；`mode=bm25`；记录 Dense/底层安全错误码 |
| 两路均无结果且无异常 | 正常返回空结果，不创建失败状态 |
| 两路均发生可恢复故障 | 抛出 `RetrievalUnavailableError`；Graph 映射为 `fatal_error.code=retrieval_unavailable` 并跳过生成 |
| 任一路发生数据契约或未知编程错误 | 原异常立即传播，不执行静默降级 |
| Reranker 已知失败 | 保留 RRF/候选顺序，`reranker_degraded=true` |

## 修改文件

- `backend/src/rag/retrieval/exceptions.py`
- `backend/src/rag/retrieval/pipeline.py`
- `backend/src/rag/retrieval/dense.py`
- `backend/src/rag/retrieval/bm25.py`
- `backend/src/rag/retrieval/__init__.py`
- `backend/src/rag/vectorstore/chroma.py`
- `backend/src/rag/vectorstore/exceptions.py`
- `backend/src/rag/vectorstore/__init__.py`
- `backend/src/rag/embeddings/client.py`
- `backend/src/agent/nodes.py`
- `backend/tests/test_retrieval_pipeline.py`
- `backend/tests/test_workflow_failure_contract.py`
- `backend/tests/test_bm25_retriever.py`
- `backend/tests/test_chroma_vectorstore.py`
- `backend/tests/test_embedding_client.py`
- `backend/tests/test_langfuse_tracing.py`
- `backend/tests/test_rag_service.py`
- `docs/day6_task01_acceptance.md`

## 测试覆盖

- Dense 失败 / BM25 成功与 BM25 失败 / Dense 成功。
- Embedding request 异常转换；非法 Embedding response 不降级。
- BM25 陈旧索引和 tokenizer I/O 故障转换。
- Chroma transport 故障转换与对外信息脱敏。
- 双路失败总体异常和 Graph fatal 状态。
- 空结果与系统失败区分。
- 未知 `RuntimeError`、Vector Store 非法响应不被吞掉。
- diagnostics 模式、计数、阶段标志、脱敏与请求隔离。
- Reranker 回退和 Langfuse warning 回归。

## 验证结果

在 `backend` 目录执行：

```text
uv run pytest -q tests/test_retrieval_pipeline.py
37 passed in 10.44s

uv run pytest -q tests/test_workflow_failure_contract.py
11 passed in 7.84s

uv run pytest -q
393 passed, 3 skipped in 42.89s
```

3 项 skip 为项目已有的可选外部服务 smoke 测试，不需要真实凭据的离线测试全部通过。

人工检查：

- `git diff --check` 通过。
- Pipeline 未新增 `except Exception`；只捕获类型化路径异常。
- Embedding Client 不再用宽泛捕获包装未知编程错误，只转换 OpenAI `APIError`。
- diagnostics 只包含 chunk ID、分数、计数、耗时、布尔标志和安全错误码，不包含 query、API key、文档正文或原始 Provider 响应。
- 单路结果仍使用原 `SearchHit`，保留 dense/BM25/fused/rerank 分数字段契约。

## 未解决项与剩余风险

- Chroma 当前只把明确的 `InternalError`、`QuotaError`、`RateLimitError` 和 `httpx.TransportError` 视为可恢复；后续若远端部署使用其他 transport，需要在适配器边界显式补充类型，不能用宽泛捕获。
- BM25 tokenizer 仅将 I/O 和 Unicode 运行故障视为可恢复；第三方 tokenizer 若定义专用运行异常，应显式映射。
- 本任务未实现 FastAPI/SSE；`WorkflowFailure.code` 已作为 D6-06 的唯一稳定输入准备完毕。
