# D6-06：聊天 SSE 协议与真实 Token 流式输出

## 目标

实现 `POST /api/chat/stream`，将 Router、Query Rewrite、Retrieval/Rerank、最终答案 Token、Sources、完成状态通过稳定 SSE 协议发送给客户端。

最终答案必须使用 LLM Provider 的真实 streaming 能力逐增量输出；禁止先生成完整答案再按字符/单词切片伪装流式。

## 上下文

技术规格要求事件：

```text
route
rewrite
retrieval
token
sources
done
```

Day5 审查补充要求：

- 未知检索异常必须映射为结构化 `error` / `done`，连接不能无说明中断；
- API 状态必须区分 `request_id`、`trace_id`、`tracing_enabled`、`trace_exported`；
- Sources 必须直接使用 ContextBuilder 的 `context_sources`，不能从原始 hits 重算；
- 当前节点以同步一次性文本为主，不能只给 `graph.invoke()` 套 StreamingResponse；
- SSE 客户端中断属于必须测试的错误场景。

## 范围

### 1. 请求模型与边界

请求至少包含：

```json
{
  "question": "...",
  "knowledge_base_id": "technical_docs",
  "chat_history": []
}
```

要求：

- 问题去除首尾空白后不能为空；
- 限制问题长度、历史条数和单条长度；
- 统一裁剪 Router、Rewrite、Direct Answer 使用的历史窗口；
- MVP 只接受配置的默认 knowledge base；
- 对输入错误返回普通 JSON 4xx，不进入 SSE。

### 2. 统一 SSE 事件模型

定义类型化事件，不允许各层手拼不一致字典。至少包括：

- `route`：`need_retrieval`、安全的 `reason`；
- `rewrite`：`rewritten_query`；
- `retrieval`：请求级 diagnostics 与脱敏 hit 摘要；
- `token`：增量文本；
- `sources`：ContextBuilder 实际使用来源；
- `error`：安全错误码、消息、是否可重试；
- `done`：请求终态、request ID、真实 trace 状态。

建议 `done`：

```json
{
  "status": "success|failed|cancelled",
  "request_id": "...",
  "trace_id": null,
  "tracing_enabled": false,
  "trace_exported": false
}
```

SSE 格式必须正确：事件名、JSON data、空行终止；中文使用 UTF-8。

### 3. 固定事件顺序

Direct 分支：

```text
route → token* → done
```

RAG 分支：

```text
route → rewrite → retrieval → token* → sources → done
```

失败：

```text
已成功产生的过程事件 → error → done(status=failed)
```

取消：

```text
停止 Provider 流与后续事件 → 完成服务端取消收尾
```

客户端已经断开时不强求继续向网络发送 `done`，但必须结束生成器、取消上游流并完成 Trace 的 cancelled 状态。

### 4. 工作流事件适配

实现一个单一 `ChatStreamingService` 或等价边界：

- 复用现有 Router/Rewrite/Retrieval/Context/Generation 业务逻辑；
- 不在 API 层复制 Prompt、RRF、Rerank、ContextBuilder 或 citation 逻辑；
- 可通过抽取共享 service 函数，让 LangGraph node wrapper 与 stream runner 调用同一实现；
- Agent 节点不要直接依赖 FastAPI/SSE 类型；
- 过程事件只能展示系统工作流结果，不展示模型私有思维链。

### 5. 真实 Token Streaming

扩展 LLM 抽象，提供类似：

```python
stream_generate(messages) -> AsyncIterator[str] | Iterator[str]
```

要求：

- 使用 OpenAI-compatible/DeepSeek 的 `stream=true`；
- 正确解析增量 delta；
- 跳过空增量；
- 合并后结果与非流式语义一致；
- Provider 超时/断流映射为类型化 generation 错误；
- 客户端取消时关闭/取消上游 stream；
- 测试使用 Fake Streaming Client，不依赖网络。

不得用完整答案字符串切片冒充 Provider streaming。

### 6. Retrieval 事件数据

可包含：

- mode；
- dense/bm25 候选数量；
- fusion/rerank 状态；
- degraded paths；
- 最终 hit 的 `chunk_id`、source、page/section、四类分数；
- 安全耗时。

不得包含：

- 完整 Prompt；
- API Key；
- Provider 原始响应；
- Python 堆栈；
- 模型隐式推理过程。

### 7. Sources

唯一来源是 ContextBuilder 返回的实际 `context_sources` / `context_chunk_ids`：

- citation ID 连续且与答案 `[S1]`、`[S2]` 一致；
- PDF 包含文件名与页码；
- Markdown 包含文件名与 section/heading path；
- 被去重或预算截断的原始 hits 不得出现在 sources 中。

### 8. HTTP/SSE Header 与断连

至少设置：

```text
Content-Type: text/event-stream; charset=utf-8
Cache-Control: no-cache
X-Accel-Buffering: no
```

实现客户端断连检测；可选 keepalive，但不要让 keepalive 破坏业务事件顺序测试。

### 9. 测试

必须覆盖：

1. Direct 事件顺序；
2. RAG 事件顺序；
3. 真正多个 Provider delta 产生多个 token 事件；
4. 禁止“完整答案切片”的回归证明；
5. ContextBuilder 去重/截断后的 sources 精确映射；
6. Reranker 降级时仍完成回答；
7. Dense 或 BM25 单路降级；
8. 双路失败：`error` → `done(failed)`；
9. Router 非法输出的保守降级；
10. DeepSeek timeout/stream 中断；
11. 客户端断连取消上游流并终止 Trace；
12. tracing disabled 时 `trace_id=null`；
13. export 失败时回答成功但 `trace_exported=false`；
14. 所有事件 JSON 可解析且不泄密；
15. SSE 响应头正确。

## 约束

- 不实现 WebSocket。
- 不把同步完整答案切片为 token。
- 不在 API 层复制整套 LangGraph/RAG 逻辑。
- 不从原始 `retrieved_documents` 重算 sources。
- 不暴露 chain-of-thought、Prompt、API Key 或服务端堆栈。
- 不实现会话持久化；`chat_history` 只在当前请求中使用。
- 不提前实现 Streamlit 或 Day7 Evaluation。

## 验证方式

至少执行：

```bash
cd backend
uv run pytest -q tests/test_llm_streaming.py
uv run pytest -q tests/test_sse_events.py
uv run pytest -q tests/test_api_chat_stream.py
uv run pytest -q
```

手工 Smoke：

```bash
curl -N -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"question":"文档中的 RRF 如何计算？","knowledge_base_id":"technical_docs","chat_history":[]}'
```

人工验收：

1. 观察 token 在答案完成前持续到达；
2. RAG 分支顺序符合契约；
3. Sources 可定位文件与页码/章节；
4. 手动中断 curl，确认服务端停止继续生成；
5. 禁用 tracing 后 `trace_id` 为空；
6. 注入 BM25 故障时仍由 Dense 回答并显示 degraded；
7. 注入双路故障时得到结构化 error 与 failed done。

## 最终交付

Codex 最终答复必须包含：

1. SSE 事件 schema 与两条分支顺序；
2. 真实 Provider streaming 的实现位置和证明；
3. 工作流复用方式，说明没有复制 Prompt/RAG 逻辑；
4. Sources 唯一映射来源；
5. 错误与取消语义；
6. 改动文件列表；
7. 专项与全量测试真实结果；
8. 一段脱敏的 curl SSE 输出样例；
9. 新增 `docs/day6_task06_acceptance.md`。
