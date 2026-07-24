# Day 6 Review Report

## Overall Status

**PASS WITH ISSUES**

## Summary

Day6 的功能范围已基本完成：FastAPI 应用基座、健康检查、文档上传、内置知识库加载、索引统计、SSE 流式问答、Streamlit UI、来源展示和 RAG 过程面板均有实际实现，且没有提前引入 Day7 的 Evaluation、Docker 或项目包装工作。文档入库继续复用唯一 Retrieval Runtime，Chroma/BM25 一致性、单路检索降级、结构化错误和来源映射的边界总体正确。

本次独立验证结果为：后端 `457 passed, 3 skipped`，前端 `20 passed`；后端语句覆盖率为 92%。三个 skip 均为显式 opt-in 的真实 LLM、Reranker、Langfuse 外部 Smoke。当前环境未配置这些凭据，因此本次审查不能独立重放真实模型端到端链路，也不把验收报告中的外部执行描述视为可重复证据。

Day6 仍有四项需要在 Day7 包装前处理的 Major 问题：浏览器主链路实际绕过 LangGraph；客户端可控的 `request_id` 可造成并发 Trace 串线；Observer 永久保留每个请求状态导致无界内存增长；生产使用的异步 Provider stream 与真实 HTTP 断连取消没有端到端测试证明。这些问题不否定 Day6 的主要功能，但会影响架构陈述、长期运行稳定性和面试可信度。

## Requirement Check

| Requirement | Status | Notes |
|---|---|---|
| D6-01 检索失败类型化与单路降级 | PASS | Dense、BM25、Vector Store 和双路失败有稳定异常契约；不可恢复错误不会被统一吞掉。 |
| D6-02 并发入库与 BM25 一致性 | PASS WITH LIMITATION | 单进程共享锁、不可变快照、stale 状态和恢复路径已实现；仍明确限制为单 Uvicorn worker。 |
| D6-03 Observability readiness | PASS WITH ISSUES | `request_id`、真实 `trace_id`、enabled/configured/available/exported 已区分；真实 Langfuse/Reranker 为 NOT RUN，且存在请求键冲突和状态无界保留。 |
| D6-04 FastAPI、lifespan、health | PASS | 导入不连接外部服务；runtime 只构建一次；health 可区分 ok/degraded/unavailable；关闭会继续清理剩余资源。 |
| D6-05 upload/load-default/stats | PASS | 文件校验、临时文件、幂等、部分失败和实时索引统计均有覆盖；上传成功后可立即检索。 |
| D6-06 SSE 与真实 token streaming 实现 | PASS WITH ISSUES | Provider `stream=true` 与 delta 转发已实现；固定事件顺序和安全错误已测试；生产异步分支及 HTTP 断连集成证据不足。 |
| D6-07 Streamlit Demo | PASS WITH ISSUES | UI 功能、增量 SSE parser、来源和过程面板均已实现；真实浏览器证据只有文字记录，没有可复放脚本或截图产物。 |
| `/api/health` | PASS | 本地 readiness，不在健康请求中调用付费外部服务。 |
| `/api/documents/upload` | PASS | PDF/Markdown、大小/MIME/策略校验、路径清理和 BM25 同步语义完整。 |
| `/api/documents/load-default` | PASS | 支持自动策略、逐文件结果、幂等和部分失败汇总。 |
| `/api/chat/stream` | PASS WITH ISSUES | Direct/RAG/失败事件协议可用，但主路径由自定义 runner 编排而不是已编译 LangGraph。 |
| Streamlit 上传、聊天、流式回答、Sources、过程面板 | PASS | 前端不持有 Provider 密钥，所有业务均经 FastAPI。 |
| Day6 范围控制 | PASS | 未加入认证、多租户、复杂文件管理、WebSocket、Docker 或正式 Evaluation。 |
| 真实 Reranker | NOT RUN | 当前未启用且未配置凭据；没有真实质量或延迟结论。 |
| 真实 Langfuse 导出/Dashboard | NOT RUN | 当前未启用且未配置凭据；没有 Dashboard 可见性证据。 |

## Findings

### Critical

- 无。

### Major

#### M1. 浏览器聊天主链路绕过已编译 LangGraph，项目展示链路存在双重编排

证据：

- `backend/src/app.py:80-89` 同时构建 `services.workflow = build_graph(...)` 和独立的 `ChatStreamingService`。
- `/api/chat/stream` 只通过 `get_chat_service()` 调用 `ChatStreamingService.stream()`；仓库中没有生产代码消费 `services.workflow`。
- `backend/src/api/chat.py:103-220` 再次手工编排 Router、Rewrite、Retrieve、Generation 和分支顺序。它复用了节点函数和消息构建器，因此没有复制 Prompt/RRF/Context 算法，但复制了工作流控制流。

影响：

- 技术规格中的 `FastAPI → LangGraph Workflow → Router/RAG` 并不是浏览器 Demo 的真实执行路径。
- Day7 Evaluation 若调用 LangGraph，而 Demo 调用 `ChatStreamingService`，两条路径可能在失败语义、Trace、历史裁剪或未来节点修改后产生漂移。
- 面试中表述“端到端 Demo 由 LangGraph 编排”会不准确；当前更准确的描述是“LangGraph 与 SSE runner 复用同一组节点逻辑”。

建议：Day7 前明确唯一可展示的编排真相。优先让流式接口消费 LangGraph 的流式/自定义事件能力；若保留双 runner，则应抽取纯业务步骤、增加 Graph 与 SSE 的契约一致性测试，并在 README 中如实解释原因和边界。

#### M2. 客户端提供的 `X-Request-ID` 被直接作为内部 Trace 主键，并发重复 ID 会造成请求串线

证据：

- `backend/src/app.py:121-122` 接受客户端 `X-Request-ID`，只截断长度，不保证格式或唯一性。
- `backend/src/observability/tracing.py:157,186-187` 以该 ID 作为 `_statuses` 字典唯一键。
- `backend/src/observability/langfuse.py:32,43,47,80` 同样以该 ID 保存、查找和弹出 Langfuse 根 observation。
- 独立探针连续两次调用 `start_request("same-request-id")` 得到两个不同 trace ID，但第二次状态覆盖第一次，`get_status()` 只能返回第二个 Trace。

影响：两个并发请求若复用同一 Header，后一个请求会覆盖前一个状态/root；前一个完成时可能结束后一个 Langfuse 根 Trace，导致 parent 关系、导出状态和 `done.trace_id` 错配。这违反 D6-03 的请求隔离目标，也可能让不同用户请求在观测系统中串线。

建议：内部始终生成服务端唯一 request ID；如需保留调用方 ID，将其作为独立 `client_request_id`/correlation metadata，不能作为 Observer 的唯一生命周期键。补充相同客户端 ID 的并发隔离测试。

#### M3. Trace Observer 永久保留所有完成请求状态，长时间运行会无界增长

证据：

- `SafeTraceObserver` 在 `backend/src/observability/tracing.py:157` 创建进程级 `_statuses`。
- 每次请求在 `backend/src/observability/tracing.py:186-187` 写入状态；`finish_request()` 只更新状态，没有删除、TTL 或容量上限。
- 即使 tracing disabled，`NoOpTraceObserver` 也会为每次聊天写入状态。
- 独立探针完成 1000 个 No-op 请求后，`_statuses` 仍保留 1000 项。

影响：常驻 FastAPI 服务会随请求数持续增长内存；启用真实 Trace 时还会长期保留 request/trace 关联。该问题在短时 Demo 和现有测试中不明显，但会削弱工程化展示可信度。

建议：`finish_request()` 返回终态快照后立即释放内部状态，或使用有界 TTL/LRU 存储；为未正常结束的请求增加回收策略，并添加大量完成请求后的容量测试。

#### M4. 测试没有覆盖生产实际采用的异步 stream 分支，也没有证明 HTTP 断连会取消上游 Provider

证据：

- 生产 `DeepSeekClient` 提供 `astream_generate()`，因此 `backend/src/api/chat.py:262-276` 默认选择异步分支。
- 后端覆盖率报告显示该异步分支 `264-276` 全部未执行；当前 `ChatStreamingService` 测试 Fake 只实现同步 `stream_generate()`。
- `test_client_cancellation_closes_provider_and_trace` 直接对 service async generator 调用 `aclose()`，证明的是服务层清理，不是 ASGI/HTTP 客户端断开。
- `test_api_chat_stream.py` 使用 `TestClient.post()` 后读取完整 `response.text`，没有在 token 中途关闭 socket；`request.is_disconnected()` 的返回路径也未覆盖。

影响：当前测试分别证明了 AsyncOpenAI client 可以关闭、service 同步 fallback 可以取消、HTTP 正常流可以完成，但没有证明这三层组合后的生产行为。若 Starlette 取消传播、AsyncOpenAI 关闭或 trace cancelled 收尾出现集成问题，现有 457 项测试仍可能全部通过。

建议：增加一个实现 `astream_generate()` 的 Chat service 测试，再使用真实 ASGI server 或可控 transport 在首个 token 后断开连接，断言 async Provider `aclose()`、后续事件停止、Trace outcome 为 cancelled。该项应作为 D6-06 的验收门槛，而不是只依赖单层单元测试。

### Minor

#### m1. 每个启用 Trace 的请求在 async SSE 生成器内同步执行全局 `flush()`

`backend/src/observability/tracing.py:290` 在 `finish_request()` 中调用同步 `flush()`，真实实现最终执行 `backend/src/observability/langfuse.py:94` 的 `client.flush()`。`ChatStreamingService` 在事件循环中直接调用该同步方法，因此一次较慢的导出可能阻塞其他并发 SSE 请求；全局 flush 也不是严格的单请求导出确认。Demo 规模下可接受，但 Day7 应避免把它描述为高并发设计。

#### m2. Day6 真实端到端证据不可完全复放

`docs/day6_acceptance_report.md` 记录了本地 backend/frontend、真实 token、PDF/Markdown 来源和 Rewrite 结果，但没有提交 Smoke 脚本、命令输出文件或截图。当前审查环境又没有 LLM/Embedding 凭据，因此只能确认代码和离线 Fake 契约，不能独立验证报告中的真实 Provider 执行。两张截图也仅为“建议清单”，不是交付物。

#### m3. 外部能力仍只有 readiness 契约，没有真实集成证据

真实 Reranker 和 Langfuse 均诚实标记为 NOT RUN，这是正确做法；但在 Day7 README、简历和面试材料中只能表述为“已实现可选适配器、降级和离线契约”，不能表述为“真实重排收益已验证”或“Langfuse Dashboard 已完成全链路观测”。

#### m4. 共享外部 HTTP 客户端没有纳入 lifespan 关闭契约

`DeepSeekClient` 的同步/异步 OpenAI client 和 `EmbeddingClient` 的 OpenAI client 均为懒创建，但 `ApplicationServices` shutdown 只关闭 Observer 与 Chroma Runtime。进程退出时操作系统会回收连接，但重复 lifespan、热重载或嵌入式运行会留下连接池生命周期不明确的问题。建议在 Day7 容器化前补充显式 `close()/aclose()` 语义。

## Architecture Assessment

架构主体仍然是小而清晰的 RAG 系统，没有引入 AnyKB 的多租户、用户系统、复杂 Agent、数据库或无关依赖。以下边界符合技术规格：

- API 路由只负责 HTTP/SSE 边界，Parser、Chunker、Embedding、Chroma 和 BM25 没有在路由中重新装配。
- `build_retrieval_runtime()` 仍是 Chroma、BM25、Dense、Hybrid、Reranker 和 Ingestion 的唯一装配入口。
- 文档提交阶段使用共享单进程锁，成功响应前完成 Chroma 写入和 BM25 快照发布；stale 时不会伪装成正常 hybrid。
- Agent/API 均通过统一 Retriever、`SearchHit`、`RetrievalResult` 和 ContextBuilder 来源契约工作。
- Sources 直接来自 ContextBuilder 实际使用结果，没有从原始 retrieval hits 二次推导。
- Langfuse SDK 仍隔离在 Adapter，业务节点没有直接依赖 Provider SDK。
- Streamlit 只管理浏览器会话和展示，不直接调用 RAG/LLM，也不保存服务端密钥。

主要架构偏差是 M1：LangGraph 已编译但不在 Demo 主链路上执行。其次是 M2/M3 暴露出的 Observability 生命周期设计问题。总体基础可以支撑 Day7，但必须先保证“代码实际路径”和“README/面试架构图”一致。

## Test Assessment

测试总体质量高，不能只用数量评价：

- 检索异常测试区分单路故障、双路故障、空结果、不可恢复错误和 Reranker 降级。
- 并发 ingestion 使用 Event/锁进行确定性交错，不依赖 sleep；BM25 generation、stale 和恢复均有行为断言。
- 文档 API 覆盖 Markdown/PDF、页码、立即检索、并发、幂等、临时目录、大小/类型/策略、部分失败和脱敏错误。
- SSE 测试验证 Direct/RAG/失败事件顺序、多个 provider delta、不调用非流式 `generate()`、来源去重/预算截断和 export failure。
- 前端 parser 覆盖任意 UTF-8 字节边界、CRLF、多事件、注释、非法 JSON/UTF-8；状态机验证部分回答保留和 sources 单一来源。
- Streamlit AppTest 验证 Fake Backend 契约、错误展示和后端不可达时页面不崩溃。

本次实际命令：

```text
cd backend
uv run pytest -q
457 passed, 3 skipped, 1 warning in 52.24s

uv run pytest -q --cov=src --cov-report=term-missing
TOTAL 3325 statements, 266 missed, 92%
457 passed, 3 skipped, 1 warning in 49.13s

cd frontend
uv run pytest -q
20 passed in 19.01s
```

三个 skip：

1. 外部 LLM structured Smoke；
2. 外部 Reranker Smoke；
3. 外部 Langfuse Smoke。

测试的主要缺口是 M4。此外，当前未启用 branch coverage 或最低覆盖率门槛；`api/chat.py` 84%、`api/documents.py` 82%，未覆盖行主要集中在 async stream 清理、断连、Observer 异常和部分恢复路径。92% 语句覆盖率已经很好，但不能替代这些高风险分支的行为测试。

## Day7 Impact

Day7 可以开始 Evaluation/Docker/README 准备，但在发布包装前应先关闭或明确以下事项：

1. 决定 Evaluation 与 Demo 使用同一 LangGraph/stream runner，避免指标评估一条路径、浏览器展示另一条路径。
2. 修复内部 request ID 唯一性和 Observer 状态回收，否则真实 Langfuse 并发演示不可信。
3. 增加生产 async streaming + HTTP disconnect 集成测试。
4. Docker/Compose 先固定单 worker；当前 BM25 一致性锁不能跨进程/实例协调。
5. 若镜像启用 Langfuse，必须安装 `observability` extra，并明确 Reranker/Langfuse 无凭据时的 degraded/unavailable 状态。
6. README 不得把当前 NOT RUN 的外部能力写成真实 PASS；正式 Evaluation 也不能使用手工 fixture 代替真实模型结果。
7. 保存可复现的 Demo 命令、脱敏配置、至少两张截图和一次真实流式输出证据。

## Interview Value Assessment

Day6 显著提升了面试展示价值：候选人可以展示上传即问、结构化 API 错误、SSE 原生 delta、精确 PDF 页码/Markdown 章节引用、Hybrid/Rerank 降级、BM25 并发一致性和可诊断 health。这些内容比单纯把模型调用包进 Web 页面更有工程说服力。

当前最容易被追问的短板是：

- “浏览器请求是否真的经过 LangGraph？”——当前答案是否定的，必须如实解释双 runner。
- “两个请求 ID 一样会怎样？”——当前会污染 Trace 生命周期。
- “断开浏览器后 Provider 是否一定停止计费？”——现有测试尚未在 HTTP + async Provider 组合层证明。
- “Langfuse/Reranker 实际效果在哪里？”——当前只有离线契约，没有真实外部证据。

关闭 M1-M4 并补充真实演示证据后，Day6 会成为很强的端到端 RAG 工程展示；在此之前，面试材料应避免超出证据范围的表述。

## Recommendation

**Fix Before Day7 Finalization**

可以并行准备 Day7 数据集和文档框架，但在生成最终 Evaluation、Docker Demo、README、简历描述和演示视频前，应优先：

1. 统一或准确声明 LangGraph 与 SSE 的真实编排路径；
2. 修复 request ID 冲突和 Trace 状态无界保留；
3. 补充生产 async Provider + HTTP 断连取消测试；
4. 有凭据时执行真实 Reranker/Langfuse Smoke，并保存可核验的脱敏证据。
