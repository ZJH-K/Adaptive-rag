# D6-03：Langfuse 请求生命周期、导出状态与外部服务就绪度

## 目标

修正当前 Langfuse Adapter 的请求级生命周期语义，并建立可供 Day6 健康检查和 SSE 使用的显式观测状态：本地请求 ID 与真实 Langfuse Trace ID 必须区分，启用但缺依赖/缺配置/导出失败必须可诊断，不能静默 No-op 后仍向前端返回看似有效的 Trace ID。

同时完善 Reranker 与 Langfuse 的 opt-in Smoke 入口，使有凭据时可以生成真实、可复现证据；无凭据时诚实跳过。

## 上下文

Day5 审查报告的 Major M1、M2 指出：

- 真实 Reranker 和 Langfuse Smoke 均未执行；
- Langfuse 为可选依赖，启用但未安装时会静默降级；
- No-op 仍生成 32 位 `trace_id`；
- 当前 observations 在业务阶段结束后才创建，时间轴不代表真实业务持续时间；
- 缺少 `chat_request` 根 observation、父子关系和可信的完成/导出状态；
- 现有 Smoke 只断言本地 ID 长度，不能证明 Dashboard 可见。

Day6 前端需要展示 Trace 状态，但不得误导用户。

## 范围

### 1. 定义观测结果契约

建立请求级状态，至少区分：

```text
request_id                # 始终存在的本地关联 ID
tracing_enabled
tracing_configured
tracing_available
trace_id                  # 仅在 Provider 创建真实 Trace 后存在
trace_exported            # flush/export 成功后的明确状态
trace_error_code          # 脱敏安全码
```

禁止 No-op Observer 伪造 Langfuse `trace_id`。

### 2. 修正根 Trace 与阶段生命周期

一次问答应形成：

```text
chat_request root
├── router
├── query_rewrite（仅 RAG）
├── dense_retrieval（仅 RAG）
├── bm25_retrieval（仅 RAG）
├── rrf_fusion（仅 Hybrid）
├── rerank（启用且有候选时）
└── final_answer
```

要求：

- observation 在业务操作开始前创建，在完成/失败后结束；
- 父子关系明确；
- 记录真实业务耗时，而不是只记录事件发送耗时；
- 请求成功、失败、取消具有不同终止状态；
- 直接回答分支不伪造 Rewrite/Retrieval/Rerank 节点；
- payload 继续脱敏，不记录 API Key、完整 Prompt、私有思维链。

如果当前 Observer 抽象不足，可做最小重构，但不要让 Langfuse SDK 调用散落进 Agent 节点。

### 3. 明确创建与降级策略

`build_trace_observer()` 或等价工厂必须区分：

- disabled：正常 No-op；
- enabled 但未配置：unavailable，返回明确状态/告警；
- enabled 且配置但缺少依赖：unavailable，不能静默；
- SDK 初始化失败：unavailable，记录安全错误码；
- 运行中 export 失败：核心回答不失败，但 `trace_exported=false`；
- 正常：返回真实 trace ID 和导出状态。

### 4. 生命周期接口

为 FastAPI lifespan 提供：

- startup readiness/status；
- request start/finish/cancel；
- `flush()`；
- `shutdown()`。

保证 flush/shutdown 失败不会破坏主服务关闭，但要可诊断。

### 5. Reranker 就绪度

提供与健康检查一致的状态：

```text
enabled
configured
available
model
last_error_code
```

`.env.example` 默认值必须避免“enabled=true 但无 API key，每次都必然降级”的误导状态。可以默认关闭，或通过工厂自动把未配置状态显示为 unavailable；选择一种并说明。

### 6. 外部 Smoke

完善 opt-in Smoke：

- 真实 Reranker：自然问题 + 至少 3 个候选，输出脱敏后的前后排名、模型和执行日期；
- 真实 Langfuse：创建一个根 Trace 和至少两个子 observation，flush 后输出真实 trace ID；
- Smoke 必须由显式环境变量开启；
- 无凭据时 `SKIPPED`；
- 不能把 Fake Observer 或人工 score 记录成真实成功；
- Dashboard 可见性仍需人工确认，报告中必须标为人工验收项。

## 约束

- 不实现 FastAPI Endpoint、SSE 或 Streamlit。
- 不把 Langfuse SDK 绑定到业务层或 Agent 节点。
- 不要求在无凭据环境中产生真实 Smoke PASS。
- 不因为观测失败而阻断核心问答。
- 不记录完整问题/答案以外的敏感配置、Provider 原始响应或堆栈。
- 不将人工 fixture 的排序提升描述为真实质量收益。

## 验证方式

离线至少执行：

```bash
cd backend
uv run pytest -q tests/test_tracing.py
uv run pytest -q tests/test_langfuse.py
uv run pytest -q tests/test_reranker.py
uv run pytest -q
```

有凭据时再执行项目定义的 opt-in 命令，例如：

```bash
RUN_EXTERNAL_RERANKER_SMOKE=1 uv run pytest -q tests/test_reranker_smoke.py -s
RUN_EXTERNAL_LANGFUSE_SMOKE=1 uv run pytest -q tests/test_langfuse_smoke.py -s
```

人工检查：

1. disabled 时只有 `request_id`，没有伪造 `trace_id`；
2. enabled 但缺依赖时状态明确为 unavailable；
3. 真实/模拟 SDK 中根 Trace 包含正确父子关系；
4. export 失败时回答成功、`trace_exported=false`；
5. Dashboard 中人工确认一次完整 Trace（仅在有凭据时）。

## 最终交付

Codex 最终答复必须包含：

1. 新观测状态契约；
2. 根 Trace 与子 observation 生命周期说明；
3. disabled / misconfigured / missing dependency / export failure / success 行为表；
4. Reranker readiness 语义；
5. 离线测试结果；
6. 外部 Smoke 的真实状态：`PASS`、`FAIL` 或 `NOT RUN`，不得模糊；
7. 若执行真实 Langfuse，提供脱敏 trace ID 与人工 Dashboard 验证说明；
8. 新增 `docs/day6_task03_acceptance.md`。
