# D6-02 并发入库与 BM25 索引一致性验收记录

## 一致性方案

本任务采用单进程应用级共享 `RLock`。`build_retrieval_runtime()` 创建唯一锁，并把同一个锁实例注入 `RetrievalRuntime` 和 `IngestionPipeline`。

解析、切分和 Embedding 在锁外执行；以下提交阶段在锁内完整串行化：

```text
Chroma upsert
→ 标记 BM25 needs_rebuild
→ 从 Chroma 读取最新全量 Chunk
→ 构造 BM25 不可变快照
→ 原子发布新 generation
→ 更新健康状态
→ 返回 IngestionResult
```

这适合单进程 MVP：实现简单、提交边界明确，上传返回 `done` 时 Dense 和 BM25 已同时看到本次数据，也不会引入分布式锁或后台任务基础设施。

`BM25Index` 另有 rebuild 串行锁。即使旧快照构造耗时更长，后续 rebuild 也只能在旧 rebuild 完成后构造并发布，因此旧 generation 不会在新 generation 之后覆盖它。

## 索引状态

新增不可变 `BM25IndexStatus`：

| 字段 | 含义 |
|---|---|
| `generation` | 成功发布的 BM25 快照版本 |
| `chunk_count` | 当前快照 Chunk 数量 |
| `needs_rebuild` | Chroma 可能领先于 BM25 |
| `last_successful_rebuild_at` | 最近成功重建的 UTC 时间 |
| `last_failure_code` | 最近失败的安全错误码 |
| `is_rebuilding` | 当前是否正在构造新快照 |

状态迁移：

```text
初始/启动 → rebuilding → ready
Chroma upsert → needs_rebuild
重建成功 → generation + 1, needs_rebuild=false, failure=null
重建失败 → needs_rebuild=true, failure=bm25_rebuild_failed
显式 rebuild_from_store() 成功 → ready
```

索引陈旧时，`BM25Retriever` 抛出类型化 `bm25_index_stale`。Hybrid Pipeline 临时使用 Dense-only，并通过 diagnostics 报告 `mode=dense`、`degraded_sources=(bm25,)` 和安全错误码，不会宣称正常 Hybrid。

## 上传结果契约

`IngestionResult` 现在包含：

- `status`: `done` 或 `partial`；
- `bm25_synced`: BM25 是否完成同步；
- `error_code`: 对外安全错误码；
- `index_status`: 返回时的索引状态快照。

行为：

| 场景 | 结果 |
|---|---|
| Chroma 与 BM25 均成功 | `status=done`, `bm25_synced=true` |
| Chroma 成功、BM25 失败 | `status=partial`, `error_code=bm25_rebuild_failed` |
| Parser/Embedding/Chroma 失败 | 沿用原异常契约，不返回伪成功 |
| 同文件同策略重复入库 | Chroma upsert 幂等，Chunk 数量不增长 |

## 生命周期接口

- `RetrievalRuntime.startup()`：从持久化 Chroma 恢复 BM25；
- `RetrievalRuntime.rebuild_from_store()`：显式恢复 stale 索引；
- `RetrievalRuntime.get_index_status()`：返回只读状态；
- `RetrievalRuntime.close()`：关闭 runtime 自己创建的 Chroma；
- `build_retrieval_runtime()`：仍是唯一装配入口，并在返回前完成首次恢复。

## 确定性并发测试

测试不依赖 `sleep`：

1. 并发 ingestion 使用 `Event` 阻塞第一批的全量 Chroma 读取；第二批线程已启动，但必须等待共享提交锁。释放后最终 BM25 和 Chroma 都包含两批 Chunk，generation 为 2。
2. generation 覆盖测试在旧 rebuild 的 tokenizer 中使用 `Event` 阻塞构造；新 rebuild 已启动但等待 rebuild 锁。释放后新快照最后发布，最终只包含新语料。
3. rebuild 期间直接读取状态，确认 `is_rebuilding=true`。

## 改动文件

- `backend/src/rag/ingestion/pipeline.py`
- `backend/src/rag/ingestion/__init__.py`
- `backend/src/rag/retrieval/bm25_index.py`
- `backend/src/rag/retrieval/__init__.py`
- `backend/src/rag/runtime.py`
- `backend/tests/test_ingestion.py`
- `backend/tests/test_bm25_index.py`
- `backend/tests/test_retrieval_runtime.py`
- `docs/day6_task02_acceptance.md`

## 测试覆盖

- 两批并发 ingestion 最终语料完整；
- 慢旧快照不能覆盖新 generation；
- rebuild 期间状态可见；
- rebuild 失败后返回 partial 且 `needs_rebuild=true`；
- 显式恢复后清除 stale/failure 状态；
- stale 期间查询明确 Dense-only 降级；
- `done` 返回前 BM25 已能命中新文档；
- 重启后首次 Hybrid 查询恢复持久化语料；
- runtime 与 ingestion 使用同一个共享锁；
- 重复入库幂等测试继续通过。

## 验证结果

在 `backend` 目录执行：

```text
uv run pytest -q tests/test_ingestion.py
16 passed in 12.07s

uv run pytest -q tests/test_retrieval_runtime.py
4 passed in 10.64s

uv run pytest -q
398 passed, 3 skipped in 33.10s
```

仓库没有 `tests/test_runtime.py`，因此按任务允许使用实际等价文件 `tests/test_retrieval_runtime.py`。3 项 skip 是已有的可选外部服务 smoke 测试；离线测试全部通过。

人工检查：

- 最终 BM25 `chunk_count` 与 Chroma `count()` 一致；
- 注入 rebuild 失败后状态不再是 ready；
- `rebuild_from_store()` 可清除 `needs_rebuild` 并恢复查询；
- 重启测试证明首次 Hybrid 查询可使用持久化 BM25；
- `git diff --check` 通过。

## 多进程限制与剩余风险

- 锁只在单个 Python 进程内共享。多个 Uvicorn worker 或多个应用实例各自拥有 BM25 内存快照，无法依靠本锁互相协调。
- 当前 MVP 应以单 worker 运行写入接口。若未来需要多进程写入，应引入权威版本号与跨进程协调机制，或把 BM25 迁移到共享检索服务。
- BM25 每次受控提交仍从 Chroma 全量重建，适合当前演示规模；大语料下需要评估增量索引或后台构建，但不在本任务范围内。
