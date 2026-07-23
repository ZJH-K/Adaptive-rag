# Day 7 Task 01：统一 LangGraph 与 SSE 生产编排

## 目标

消除当前“已编译 LangGraph”和“手写 `ChatStreamingService` 控制流”并存的双重编排，使浏览器 Demo、API、自动化测试和后续 Evaluation 使用同一套权威工作流逻辑。

完成后，`/api/chat/stream` 的 Router、Direct/RAG 分支、Query Rewrite、Retrieval、Context、Generation 顺序必须由 LangGraph 或其唯一的共享工作流定义驱动，而不是在 API 层再次手写一套等价 `if/else` 流程。

## 上下文

Day6 审查发现：

- 应用同时构建 `services.workflow = build_graph(...)` 和独立 `ChatStreamingService`；
- 生产 `/api/chat/stream` 未实际消费已编译 LangGraph；
- API 层重新编排 Router、Rewrite、Retrieve、Generate；
- 若 Day7 Evaluation 调用 LangGraph，而浏览器 Demo 继续走另一套 runner，两条链路会在失败语义、Trace、历史裁剪和事件字段上逐渐漂移。

技术文档声明的主链路是：

```text
FastAPI /chat/stream
→ LangGraph Workflow
→ Router
→ Direct 或 Rewrite → Retrieve → Generate
→ SSE
```

本任务要让代码实际路径与该架构陈述一致。

## 范围

### 必须实现

1. 明确一个唯一的工作流权威来源：优先使用已编译 LangGraph 作为生产编排核心。
2. 让 `/api/chat/stream` 消费该工作流的状态流、节点事件或自定义事件。
3. 保留现有 SSE 对外事件契约：
   - `route`
   - `rewrite`（仅 RAG 分支）
   - `retrieval`（仅 RAG 分支）
   - `token`
   - `sources`（有来源时）
   - `done`
   - `error`（失败时）
4. Direct 分支必须保持零检索；RAG 分支顺序必须保持 Rewrite → Retrieve → Generate。
5. Token 必须继续来自 Provider 流式 delta，不能退回“先生成完整答案再按字符切分”。
6. 可以保留一个薄的 SSE Adapter，但它只能做：
   - LangGraph/节点事件到 SSE 的格式映射；
   - 客户端断连检测；
   - HTTP 层错误包装。
7. 删除、收敛或弃用 API 层重复的工作流控制逻辑，避免两套分支判断。
8. Evaluation 后续应能复用同一工作流入口或同一纯业务工作流定义。
9. 增加自动化测试，证明 Graph 与 SSE 路径在以下方面一致：
   - Router 结果；
   - Rewrite Query；
   - Retrieval 输入；
   - Context/Sources；
   - Direct/RAG 节点顺序；
   - 失败分类。

### 可接受的实现方式

- LangGraph `astream` / `astream_events`；
- 通过节点内自定义事件或 callback 发送过程事件；
- 将节点逻辑抽成纯函数后，由 LangGraph 作为唯一控制流，SSE 仅监听执行事件。

### 不包含

- 不修改 Hybrid、RRF、Reranker 算法；
- 不改变现有公开 API 请求字段；
- 不新增 WebSocket；
- 不重做 Streamlit UI；
- 不在本任务处理 Request ID 状态回收或 HTTP 断连测试细节，它们分别属于 Task 02、Task 03。

## 约束

1. 不允许保留两套独立的 Router/Rewrite/Retrieve/Generate 分支编排并仅用注释解释。
2. Agent/API 不得直接感知 Chroma、BM25、RRF 或 Reranker Provider 细节。
3. Sources 必须继续以 ContextBuilder 的 `context_sources` / `context_chunk_ids` 为唯一事实来源，禁止从原始 hits 重新推导。
4. Direct 分支不得为了生成过程事件而调用 Retriever。
5. 保持现有结构化错误语义，不得把未知编程错误全部吞掉并伪装成空检索。
6. 不得暴露模型私有思维链；过程事件只能展示 Router 结论、Rewrite 文本、检索结果和可观察状态。
7. 尽量保持现有测试兼容；若必须调整接口，需同步更新所有调用方并在完成说明中列出迁移原因。

## 验证方式

### 专项测试

至少新增或更新以下测试：

1. 通用问题通过生产 SSE 入口：
   - 事件顺序为 `route → token... → done`；
   - Retriever 调用次数为 0。
2. 文档问题通过生产 SSE 入口：
   - 事件顺序为 `route → rewrite → retrieval → token... → sources → done`；
   - rewritten query 确实传给 Retriever。
3. Graph 与 SSE 使用相同输入时：
   - `need_retrieval`、`rewritten_query`、实际 Context Chunk IDs 相同。
4. 空检索结果：
   - 不调用有依据生成；
   - 返回安全、明确的无依据结果或结构化错误，行为与 Graph 一致。
5. Retriever/Reranker/LLM 已知故障：
   - SSE 与 Graph 的失败分类一致。
6. 不再有生产代码构建但从不消费的 `services.workflow`，或有明确测试证明它是生产路径。

### 建议命令

```bash
cd backend
uv run pytest -q tests/test_agent_graph.py tests/test_api_chat_stream.py tests/test_chat_streaming_service.py
uv run pytest -q

cd ../frontend
uv run pytest -q
```

### 人工检查

- 搜索生产代码，确认不存在第二套完整 Router → Rewrite/Retrieve → Generate 手写控制流。
- 启动应用后分别发送 Direct 与 RAG 问题，确认事件顺序与技术文档一致。

## 最终交付

1. 统一后的生产工作流实现；
2. SSE 事件适配层；
3. Graph/SSE 契约一致性测试；
4. 更新的相关架构注释或开发文档；
5. 一份任务完成说明，明确：
   - 生产请求实际经过哪条路径；
   - 旧双 runner 如何被删除或收敛；
   - Token 流式生成如何保留；
   - 仍存在的限制。
