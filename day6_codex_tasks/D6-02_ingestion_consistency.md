# D6-02：并发入库与 BM25 索引一致性

## 目标

保证 Day6 文档上传接口在同一应用进程内并发执行时，不会让旧 BM25 快照覆盖新快照；上传成功返回后，用户立即发起查询时，Dense 与 BM25 都能看到本次入库结果。

同时让 `needs_rebuild` 成为可被运行时消费和恢复的状态，而不是只被设置、从不处理的标记。

## 上下文

Day5 审查报告的 Major M4 指出：

- Chroma upsert、读取全量 Chunk、BM25 rebuild 之间没有请求级串行化；
- 两次上传交错时，较早读取的旧语料可能最后发布；
- `BM25Index.needs_rebuild` 没有被查询路径或运行时恢复路径消费；
- 当前测试只证明单次快照发布原子性，没有证明并发 ingestion 最终语料完整。

Day6 的技术验收要求是“上传完成后可以立即提问”。因此 API 不能在 Chroma 已写入但 BM25 仍旧或重建失败时无条件返回 `status=done`。

## 范围

### 1. 选择并实现单进程一致性方案

在 MVP 边界内实现清晰方案，推荐：

```text
应用级 ingestion/rebuild 锁
→ Chroma upsert
→ 获取最新全量 Chunk 快照
→ 构造新 BM25 不可变快照
→ 原子发布
→ 标记索引版本/健康状态
→ 返回成功
```

也可以采用版本号校验方案，但必须证明旧版本永远不能覆盖新版本。不要引入 Redis、Kafka、分布式锁或后台任务队列。

### 2. 定义索引状态

提供请求安全的状态对象或只读快照，至少包含：

- `generation` 或等价版本；
- `chunk_count`；
- `needs_rebuild`；
- 最近一次成功重建时间；
- 最近一次失败的安全错误码；
- 当前是否正在重建。

状态将供 D6-04 健康检查和 D6-05 上传响应使用。

### 3. 消费 `needs_rebuild`

定义并实现明确恢复路径：

- 应用启动时从持久化 Chroma 重建；
- 入库重建失败后标记 `needs_rebuild=true`；
- 后续显式恢复操作或下一次受控查询/入库触发重建；
- 重建成功后清除标记并更新 generation；
- 当索引陈旧时，Hybrid 不得静默宣称“正常 hybrid”。

允许在恢复期间临时 Dense-only，但必须通过 diagnostics/health 明确标记 degraded；如果不能保证安全读取，也可让请求返回类型化 unavailable 错误。选择一种并写入文档和测试。

### 4. 明确上传成功语义

Ingestion Service 返回结构化结果，至少区分：

- 完整成功：Chroma 与 BM25 均已更新；
- 向量写入成功但 BM25 刷新失败：不得返回普通 `done`；
- 解析/Embedding/Chroma 失败：沿用现有失败契约；
- 重复文件：保持幂等，不无限增加 Chunk。

本任务只实现服务层契约，不实现 HTTP Endpoint。

### 5. 生命周期接口

为后续 FastAPI lifespan 提供明确接口，例如：

- `runtime.startup()` / `rebuild_from_store()`；
- `runtime.close()`；
- `runtime.get_index_status()`。

保持 `build_retrieval_runtime()` 为唯一装配入口，不在 API 层重新构造第二套 Chroma/BM25 对象。

### 6. 测试

必须包含：

1. 两个并发 ingestion 交错执行后，最终 BM25 包含两批 Chunk；
2. 较旧快照构造更慢时也不能覆盖新 generation；
3. rebuild 失败后 `needs_rebuild=true`；
4. 恢复成功后标记清除且查询可使用新文档；
5. 上传成功返回前，BM25 已经可命中新文档；
6. Chroma 已写入、BM25 失败时返回部分失败/降级状态；
7. 重启后首次查询继续使用恢复后的 BM25；
8. 现有幂等入库测试不回归。

## 约束

- 只保证单进程 MVP；必须在文档中明确多进程部署限制。
- 不引入外部锁、消息队列、后台 worker 或增量持久化 BM25 服务。
- 不修改 Parser/Chunker 的算法行为。
- 不通过睡眠时间碰运气验证并发；测试应使用 Barrier/Event/Fake 钩子确定性交错。
- 不在查询时每次无条件重建全量 BM25。
- 不提前实现文档 HTTP API 或 Streamlit。

## 验证方式

至少执行：

```bash
cd backend
uv run pytest -q tests/test_ingestion.py
uv run pytest -q tests/test_runtime.py
uv run pytest -q
```

人工验证：

1. 运行一个确定性并发测试，检查最终 BM25 `chunk_count` 与 Chroma 一致；
2. 注入 BM25 rebuild 失败，检查状态不再显示 ready；
3. 调用恢复接口，确认 `needs_rebuild` 清除；
4. 模拟应用重启，确认首次 Hybrid 查询包含持久化文档；
5. 检查锁的作用域是应用共享 runtime，不是每次请求新建。

## 最终交付

Codex 最终答复必须包含：

1. 一致性方案和为什么适合单进程 MVP；
2. 改动文件列表；
3. 索引状态字段及状态迁移说明；
4. 并发测试的确定性交错方式；
5. 专项与全量测试真实结果；
6. 多进程/多实例已知限制；
7. 新增 `docs/day6_task02_acceptance.md`。
