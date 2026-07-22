# D5-05 Langfuse Tracing Report

## Changed Files

- `backend/src/observability/tracing.py`：Provider-neutral TraceObserver、统一脱敏、No-op 和线程安全 Fake。
- `backend/src/observability/langfuse.py`：Langfuse Python SDK v4 Adapter 与配置工厂。
- `backend/src/observability/__init__.py`：公开 observability 接口。
- `backend/src/agent/graph.py`、`backend/src/agent/nodes.py`：请求级 trace 生命周期和全链路 observation。
- `backend/src/rag/retrieval/pipeline.py`：增加无正文的请求级阶段排名/分数快照。
- `backend/src/config.py`、`.env.example`：增加可选 Langfuse 和隐私配置。
- `backend/pyproject.toml`、`backend/uv.lock`：增加 `observability` 可选依赖组，锁定 Langfuse v4。
- `backend/tests/test_langfuse_tracing.py`：Fake/Adapter/并发隔离/降级/脱敏测试。
- `backend/tests/test_langfuse_smoke.py`：默认跳过的真实连接 Smoke。

## Implementation Summary

### Trace 拓扑

Direct 分支：

```text
trace_id
├── generation: router
└── generation: direct_answer
```

RAG 分支：

```text
trace_id
├── generation: router
├── generation: query_rewrite
├── span: dense_retrieval
├── span: bm25_retrieval
├── span: rrf_fusion
├── generation: rerank
├── span: context_build
└── generation: final_answer
```

Langfuse v4 使用 observation-first 模型，Trace 是共享 `trace_id` 的 observation 集合，不再需要单独创建和关闭 Trace 对象。每个 observation 使用 SDK context manager 打开并在当前节点内关闭；终态同时调用 provider-neutral `finish_trace()`，Fake 可验证请求已完成。`trace_id` 始终写回 `AgentState`，供 Day 6 返回。

### 抽象与依赖边界

- `TraceObserver` 是业务代码唯一依赖的接口；
- `NoOpTraceObserver` 在未配置时仍产生 W3C 长度的请求 ID，但不发送网络数据；
- `FakeTraceObserver` 按 trace ID 保存记录并加锁，可测试交错请求；
- `LangfuseTraceObserver` 封装 `start_as_current_observation()`、`trace_context` 和 SDK update；
- Provider 的 create/start/update/end 任一阶段抛错都会被 Adapter 隔离，不改变问答结果；
- `langfuse` 位于 `[project.optional-dependencies].observability`，不是核心安装的硬依赖；
- `build_graph()` 默认根据 Settings 构建 Langfuse 或 No-op，也支持显式注入 Fake。

### 字段清单

| Observation | Input/Output/Metadata |
|---|---|
| `router` | question、history_messages、need_retrieval、route_reason、latency、degraded/fallback |
| `query_rewrite` | question、history_messages、rewritten_query、latency、degraded/fallback |
| `dense_retrieval` | query、ordered chunk IDs、dense/bm25/fused/rerank scores、count、latency、degraded/fallback |
| `bm25_retrieval` | query、ordered chunk IDs、四类分数、count、latency、degraded/fallback |
| `rrf_fusion` | 实际 Fusion 顺序、四类分数、fused count、latency、skipped |
| `rerank` | 实际最终顺序、四类分数、enabled、input/output count、latency、degraded/fallback |
| `context_build` | retrieved chunk IDs、实际 context chunk IDs、sources、latency、fatal |
| `direct_answer` / `final_answer` | question、context chunk IDs、answer、sources、latency、fatal |

Pipeline 的 `RetrievalDiagnostics` 增加 `dense_results`、`bm25_results`、`fused_results` 和 `rerank_results`。每项只含 Chunk ID 和四类分数，不含文档正文或 metadata。这样成功 Rerank 后仍可记录真实 RRF 顺序，而不是从最终 hits 反推。

### 脱敏策略

默认策略：

- question 和 answer 只记录 `[redacted;length=N]`；
- API key、secret key、Authorization、headers、prompt、context、document text 和通用 text 字段直接丢弃；
- 其他字符串按 `LANGFUSE_MAX_TEXT_CHARS` 截断；
- 候选记录只包含 Chunk ID 和分数，不上传正文；
- 错误只记录 D5-04 的安全 `error_type`、fallback 和固定 status，不记录异常文本或堆栈；
- 不记录聊天历史正文和模型思维链，只记录窗口内消息数量。

如确有需要，可分别设置：

```env
LANGFUSE_CAPTURE_QUESTION=true
LANGFUSE_CAPTURE_ANSWER=true
LANGFUSE_MAX_TEXT_CHARS=200
```

### 降级行为

- Router/Rewrite fallback：对应 generation 为 `WARNING`，记录安全 error type 和 fallback；
- Dense/BM25 单路失败：失败路径为 `WARNING`，成功路径继续记录真实结果；
- Reranker disabled：保留 `rerank` observation，标记 `enabled=false`、`skipped=true`；
- Reranker failure：`WARNING`，fallback=`candidate_order`，结果仍为实际回退顺序；
- Context/Generation fatal：终态 observation 为 `ERROR` 并正确关闭；
- Langfuse 未配置或 SDK 故障：自动 No-op/吞掉纯 telemetry 异常，D5-04 业务失败契约不变。

## Verification

专项回归：

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q `
  tests/test_langfuse_tracing.py tests/test_retrieval_pipeline.py `
  tests/test_hybrid_agent_graph.py tests/test_config.py `
  tests/test_agent_graph.py tests/test_workflow_failure_contract.py
```

结果：`73 passed in 14.42s`。

Fake 测试覆盖：

- Direct/RAG 拓扑；
- Reranker disabled/success/failure；
- Dense 单路降级；
- Generation fatal 和 observation 关闭；
- 实际 Chunk ID、分数、Fusion/Rerank 排名和 sources；
- 两个通过 Barrier 真实交错的图请求，Trace ID 与数据不串线；
- 未配置 No-op；
- SDK create/start/update 失败隔离；
- API key、header、question、answer 和文档正文脱敏。

完整验证：

```powershell
cd backend
.\.venv\Scripts\python.exe -m compileall -q src tests
.\.venv\Scripts\python.exe -m pytest -q
```

结果：`384 passed, 2 skipped in 51.65s`。两个 skip 分别是原有外部 LLM Smoke 和新增外部 Langfuse Smoke。

本地还通过 `uv sync --extra observability` 安装并核对了 Langfuse `4.14.1` 的构造函数、`start_as_current_observation()` 和 observation `update()` 签名；未发送真实 Trace。

### 真实 Smoke 执行方式

配置 `.env`：

```env
LANGFUSE_ENABLED=true
LANGFUSE_BASE_URL=https://cloud.langfuse.com
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
```

执行：

```powershell
cd backend
uv sync --extra observability
$env:RUN_LANGFUSE_SMOKE="1"
.\.venv\Scripts\python.exe -m pytest -q -s tests/test_langfuse_smoke.py
```

Smoke 只发送一个脱敏 observation，并在结束前调用 SDK `flush()`。本任务未使用真实凭证执行，因此没有保存 trace_id 或截图。

## Remaining Issues

- 未实现 Langfuse 自部署、Docker Compose、Dashboard、FastAPI、SSE 或 Streamlit。
- Langfuse v4 的后台 exporter 应在未来应用 shutdown hook 调用 `flush()`/`shutdown()`；当前真实 Smoke 显式 flush，正常长驻服务依赖 SDK 后台批量发送。
- 当前分阶段 latency 来自请求级 Pipeline 计时并写入 metadata；observation 自身的 wall-clock 区间是记录动作时间。若后续要求在 UI 时间轴上精确还原子阶段起止时间，可在 Pipeline 内加入带显式 timestamp 的 observer hook。
