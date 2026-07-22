# D6-03 Langfuse 生命周期、导出状态与外部服务就绪度验收

## 观测状态契约

新增不可变 `TracingStatus`：

| 字段 | 语义 |
|---|---|
| `request_id` | 始终存在的本地请求关联 ID |
| `tracing_enabled` | 用户是否启用 Langfuse |
| `tracing_configured` | 必需配置是否完整 |
| `tracing_available` | 当前 Observer 是否创建了真实 Provider Trace |
| `trace_id` | 仅 Langfuse 成功创建 Trace 后存在 |
| `trace_exported` | 请求结束并成功 flush 后为 true |
| `trace_error_code` | 脱敏后的稳定错误码 |

Disabled/Unavailable No-op Observer 只生成 `request_id`，不再伪造 32 位 Langfuse Trace ID。AgentState 分别保存 `request_id`、可选 `trace_id` 和 `tracing_status`，供后续健康检查与 SSE 使用。

## 根 Trace 与 observation 生命周期

Provider 可用时，`start_request()` 在 Router 执行前创建 `chat_request` 根 span。业务阶段通过 provider-neutral `start_observation()` 在操作前创建，通过 `finish_observation()` 在成功或失败后关闭。

RAG 分支拓扑：

```text
chat_request
├── router
├── query_rewrite
├── dense_retrieval
├── bm25_retrieval
├── rrf_fusion
├── rerank（仅启用且有候选）
├── context_build
└── final_answer
```

Direct 分支只创建：

```text
chat_request
├── router
└── direct_answer
```

每个离线 observation 记录 `started_at`、`ended_at`、`parent_name` 和 `outcome`。根请求支持 `success`、`failure`、`cancelled` 三种终止状态。Langfuse Adapter 使用根对象的 `start_observation()` 建立真实父子关系，SDK 调用没有散落到 Agent 节点。

## 创建、降级与导出行为

| 场景 | 行为 |
|---|---|
| disabled | 正常 No-op；有 `request_id`，无 `trace_id` |
| enabled、缺配置 | unavailable；`langfuse_not_configured` |
| enabled、配置完整、缺依赖 | unavailable；`langfuse_dependency_missing` |
| SDK 初始化失败 | unavailable；`langfuse_initialization_failed` |
| 根 Trace 创建失败 | 核心请求继续；`trace_creation_failed`，无伪造 Trace ID |
| observation start/finish 失败 | 核心请求继续；保存安全阶段错误码 |
| export/flush 失败 | 回答不失败；真实 Trace ID 保留，`trace_exported=false`、`trace_export_failed` |
| 正常 | 真实 Trace ID；请求结束 flush 后 `trace_exported=true` |

`flush()` 与 `shutdown()` 都会吞住 Provider 异常以保护主服务，但状态会记录 `trace_export_failed` 或 `trace_shutdown_failed`。

## Payload 安全

- 默认问题与答案只记录 `[redacted;length=N]`；完整捕获必须显式 opt-in。
- `api_key`、Authorization、headers、prompt、context、文档正文等字段会被删除。
- 不记录 Provider 原始响应、堆栈或私有思维链。
- 分数 observation 仅保留 Chunk ID、阶段分数、计数、耗时和安全错误码。

## Reranker Readiness

新增 `RerankerStatus`：

```text
enabled
configured
available
model
last_error_code
```

语义：

- 默认 `RERANKER_ENABLED=false`，避免无 API Key 时每次请求必然降级。
- Disabled 返回明确不可用但非故障状态。
- Enabled 且缺 API Key 返回 `UnavailableReranker`，错误码为 `reranker_not_configured`。
- Adapter 运行失败后更新安全错误码，例如 `reranker_request_failed` 或 `reranker_response_invalid`；成功后清除最近运行错误。
- 自定义 Reranker 仍可通过统一 `get_reranker_status()` 暴露兼容状态。

## 外部 Smoke

### Reranker

命令：

```text
RUN_EXTERNAL_RERANKER_SMOKE=1 uv run pytest -q tests/test_reranker_smoke.py -s
```

使用自然问题和 3 个候选，输出执行日期、模型、脱敏前后索引排名，不输出候选正文或凭据。

本次真实状态：**NOT RUN**。未设置显式 opt-in 环境变量，未调用真实 Provider。

### Langfuse

命令：

```text
RUN_EXTERNAL_LANGFUSE_SMOKE=1 uv run pytest -q tests/test_langfuse_smoke.py -s
```

Smoke 创建 `chat_request` 根 Trace、`smoke_router` 与 `smoke_answer` 两个子 observation，并要求 flush 后 `trace_exported=true`。

本次真实状态：**NOT RUN**。未设置显式 opt-in 环境变量，未生成真实 Trace ID。Langfuse Dashboard 可见性也未进行人工确认，仍是有凭据环境中的人工验收项。

## 改动文件

- `.env.example`
- `backend/src/config.py`
- `backend/src/observability/tracing.py`
- `backend/src/observability/langfuse.py`
- `backend/src/observability/__init__.py`
- `backend/src/agent/state.py`
- `backend/src/agent/nodes.py`
- `backend/src/rag/retrieval/reranker.py`
- `backend/src/rag/retrieval/__init__.py`
- `backend/tests/test_tracing.py`
- `backend/tests/test_langfuse.py`
- `backend/tests/test_langfuse_tracing.py`
- `backend/tests/test_langfuse_smoke.py`
- `backend/tests/test_reranker.py`
- `backend/tests/test_reranker_smoke.py`
- `backend/tests/test_config.py`
- `backend/tests/test_agent_contracts.py`
- `backend/tests/test_agent_rag_nodes.py`
- `backend/tests/test_hybrid_agent_graph.py`
- `backend/tests/test_day5_acceptance_integration.py`
- `docs/day6_task03_acceptance.md`

## 离线验证

在 `backend` 目录执行：

```text
uv run pytest -q tests/test_tracing.py
5 passed in 0.45s

uv run pytest -q tests/test_langfuse.py
5 passed in 0.27s

uv run pytest -q tests/test_reranker.py
32 passed in 6.60s

uv run pytest -q tests/test_langfuse_smoke.py tests/test_reranker_smoke.py
2 skipped in 3.19s

uv run pytest -q
410 passed, 3 skipped in 37.76s
```

3 项 skip 是显式 opt-in 的外部服务 Smoke。离线测试全部通过。

## 剩余风险与人工验收

- 本次没有真实凭据，因此没有声称 Langfuse Dashboard 可见或真实 Reranker 质量收益。
- `tracing_available=true` 表示 SDK 已成功创建请求 Trace，不等同于 Dashboard 最终可见；只有 `trace_exported=true` 才表示本进程 flush 成功。
- Provider 接收后异步处理失败仍需通过 Langfuse Dashboard 人工确认。
- Reranker readiness 的 `available=true` 表示配置完整且最近调用未失败，不执行额外健康探测，避免健康检查产生付费请求。
