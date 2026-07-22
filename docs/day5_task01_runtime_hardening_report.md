# D5-01 Runtime Hardening Report

## 修改文件

- `backend/src/rag/runtime.py`：新增唯一运行时装配入口。
- `backend/src/rag/retrieval/pipeline.py`：新增请求局部 `RetrievalResult`，移除共享 `last_diagnostics`，下推候选数量。
- `backend/src/rag/retrieval/dense.py`：支持请求级 `top_n` 并传给 Chroma。
- `backend/src/rag/retrieval/bm25.py`：支持请求级 `top_n`，一次查询固定使用一个索引快照。
- `backend/src/rag/retrieval/bm25_index.py`：以不可变快照原子发布重建结果，并提供 `needs_rebuild` 状态。
- `backend/src/rag/ingestion/pipeline.py`：BM25 同步失败时标记可重建状态并抛出明确异常。
- `backend/src/rag/retrieval/__init__.py`、`backend/src/rag/ingestion/__init__.py`：导出新增公开类型和工厂。
- `backend/tests/test_retrieval_runtime.py`：覆盖持久化恢复和装配配置。
- `backend/tests/test_retrieval.py`、`test_bm25_retriever.py`、`test_retrieval_pipeline.py`：覆盖 Top-N 下推、Fusion 上限和诊断隔离。
- `backend/tests/test_bm25_index.py`、`test_ingestion.py`：覆盖原子快照和失败一致性。
- `backend/tests/test_hybrid_agent_graph.py`：同步内部有界 Retriever 测试契约。

## 新的装配路径

`build_retrieval_runtime()` 是检索运行时的单一装配入口：

1. 使用 `Settings` 打开持久化 `ChromaVectorStore`；
2. 调用 `get_all_chunks()` 读取完整、确定排序的 Chunk 语料；
3. 在对外提供 Retriever 前完成 `BM25Index.rebuild()`；
4. 使用同一配置构造 `DenseRetriever`、`BM25Retriever` 和 `HybridRetrievalPipeline`；
5. 构造共享同一 Chroma 与 BM25Index 的 `IngestionPipeline`；
6. 返回 `RetrievalRuntime`，统一暴露查询、入库、显式 BM25 重建和资源关闭能力。

启动恢复失败会抛出 `RetrievalRuntimeBootstrapError`，不会静默退化为 Dense-only。

## Top-N 配置流向

```text
Settings.dense_top_n
  -> HybridRetrievalPipeline.dense_top_n
  -> DenseRetriever.retrieve(top_n=...)
  -> ChromaVectorStore.query_by_vector(top_k=...)

Settings.bm25_top_n
  -> HybridRetrievalPipeline.bm25_top_n
  -> BM25Retriever.retrieve(top_n=...)
  -> BM25 排名切片

Settings.retrieve_top_n
  -> reciprocal_rank_fusion(top_n=...)
```

Retriever 构造器默认限制仍保留，以兼容独立调用；在 Hybrid 主链路中，Pipeline 的有效配置会显式下推，避免“配置 50、底层仍取 20”。Pipeline 仍对第三方 Retriever 返回值做防御性切片，但该切片不再代替底层召回限制。

## Diagnostics 数据流

`HybridRetrievalPipeline.retrieve_with_diagnostics(query)` 返回当前请求专属的：

```text
RetrievalResult
  - hits: list[SearchHit]
  - diagnostics: RetrievalDiagnostics
```

Pipeline 不再保存 `last_diagnostics`。原有 `retrieve(query) -> list[SearchHit]` 保留，并仅适配返回 `RetrievalResult.hits`，因此 Agent 和现有 RAG Service 无需感知 Dense、BM25 或 RRF 内部细节。

## BM25 启动恢复与一致性证据

- 集成测试先把三个 Chunk 写入持久化 Chroma，关闭旧 Store，再创建全新的 `RetrievalRuntime`；首次 Hybrid 查询断言 `bm25_count == 1` 且结果包含 `bm25_score`。
- `BM25Index.rebuild()` 在锁外构造完整新语料与模型，完成后在锁内以一个 `BM25IndexSnapshot` 引用发布。查询捕获单一快照，重建期间不会混用新 Chunk 映射和旧模型。
- Chroma 写入成功而 BM25 刷新失败时，`IngestionPipeline` 抛出 `BM25IndexSyncError`，并设置 `BM25Index.needs_rebuild=True`。调用方不会收到 `status="done"`，可通过 `RetrievalRuntime.rebuild_bm25()` 从 Chroma 全量恢复。

## 测试命令与结果

专项验证：

```bash
cd backend
uv run pytest tests/test_retrieval.py tests/test_bm25_index.py \
  tests/test_bm25_retriever.py tests/test_retrieval_pipeline.py \
  tests/test_retrieval_runtime.py tests/test_ingestion.py -q
```

结果：`77 passed in 25.37s`

Day1-Day4 全量回归：

```bash
cd backend
uv run pytest -q
```

结果：`316 passed, 1 skipped in 35.36s`。跳过项仍为原有显式 opt-in 的外部 LLM Smoke；默认测试没有调用外部 API。

## 公开契约说明

- Agent 依赖的 `Retriever.retrieve(query) -> list[SearchHit]` 未改变。
- Dense/BM25 Retriever 的 `retrieve` 新增可选关键字参数 `top_n`；不传时继续使用构造器限制。
- 新增 `retrieve_with_diagnostics()` 供后续 Service、Trace 或 SSE 使用，请求事实不再从共享实例读取。

## 已知限制

- BM25 仍为进程内索引，进程启动时从 Chroma 全量恢复；未实现独立磁盘持久化或增量索引。
- Chroma 写入与 BM25 刷新不是跨存储事务。当前以明确异常、`needs_rebuild` 状态和全量恢复入口处理，不提供回滚。
- 快照发布保证单进程线程内查询不会看到半更新索引；未实现多进程协调或分布式锁。
- 本任务未接入 FastAPI 生命周期。Day6 应在应用启动时调用现有 `build_retrieval_runtime()`，而不是新增第二套装配路径。
