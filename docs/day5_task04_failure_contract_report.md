# D5-04 Workflow Failure Contract Report

## Changed Files

- `backend/src/agent/failures.py`：新增安全、稳定的 `WorkflowFailure` 数据模型和 LLM 错误分类。
- `backend/src/agent/state.py`：增加当前阶段、按顺序累积的降级事件、致命错误和答案可返回标记。
- `backend/src/agent/nodes.py`：落实 Router、Rewrite、Retrieval、Rerank、Context、Direct Answer 和 Generation 的失败语义，并统一聊天历史窗口。
- `backend/src/agent/graph.py`：Context fatal 后直接结束图，不再进入 Generation。
- `backend/src/rag/context_builder.py`：增加可识别的 ContextBuilder 错误基类和运行时错误类型。
- `backend/src/rag/retrieval/pipeline.py`：增加结构化 `degradation_codes`，供 Agent、Langfuse 和后续 SSE 直接消费。
- `backend/tests/test_workflow_failure_contract.py`：新增离线故障矩阵、事件顺序、安全性、历史裁剪和图停止测试。
- `backend/tests/test_agent_router.py`、`test_agent_rewrite.py`、`test_agent_rag_nodes.py`、`test_agent_contracts.py`：同步公开状态契约断言。

## Implementation Summary

### 统一失败数据结构

`WorkflowFailure` 是冻结的严格 Pydantic 模型，字段如下：

- `stage`：`router`、`rewrite`、`retrieval`、`rerank`、`context`、`direct_answer` 或 `generation`；
- `error_type`：稳定分类，如 `timeout`、`invalid_response`、`dense_retrieval_failed`；
- `safe_message`：不拼接原始异常的公开说明；
- `degraded`、`fatal`、`fallback_used`：明确控制流语义；
- `fallback`：确定性 fallback 名称；
- `duration_ms`：非负阶段耗时；
- `provider`、`code`：不含凭证和原始响应的安全标识。

`AgentState` 新增：

- `current_stage`；
- `degradation_events`，使用 LangGraph reducer 按节点执行顺序追加；
- `fatal_error`；
- `answer_available`。

原有 `retrieval_diagnostics`、`context_sources` 和 `context_chunk_ids` 保留，分别描述请求级检索过程以及实际进入上下文的精确来源。

### 失败矩阵

| 阶段 | 失败类型 | 行为 | 状态结果 | 后续执行 |
|---|---|---|---|---|
| Router | 非法结构化响应 | 保守选择检索 | degradation；fallback=`retrieve` | Rewrite → Retrieval |
| Router | timeout/调用失败 | 保守选择检索 | degradation；安全 LLM code | Rewrite → Retrieval |
| Rewrite | 非法结构化响应 | 使用原始问题 | degradation；fallback=`original_question` | Retrieval |
| Rewrite | timeout/调用失败 | 使用原始问题 | degradation；安全 LLM code | Retrieval |
| Retrieval | Dense 失败、BM25 成功 | 使用 BM25 | degradation；保留 diagnostics | Context → Generation |
| Retrieval | BM25 失败、Dense 成功 | 使用 Dense | degradation；保留 diagnostics | Context → Generation |
| Retrieval | Dense 与 BM25 均失败 | 返回空 hits/context，不伪造来源 | 两个有序 degradation event | 返回 no-evidence，不调用 LLM Generation |
| Rerank | 公开 `RerankerError` | 保留 RRF/Dense 候选顺序，不伪造 rerank score | degradation；fallback=`candidate_order` | Context → Generation |
| Context | `ContextBuilderError` | 清空 context/source，返回安全错误结果 | fatal；`answer_available=true` | 图在 Retrieve 后结束 |
| Generation | LLM timeout/调用/响应失败 | 返回固定安全错误结果 | fatal；`answer_available=true` | 图结束 |
| Direct Answer | LLM 失败 | 返回固定安全错误结果，不转入检索 | fatal；`answer_available=true` | 图结束 |

只捕获公开、可预期的 provider/组件异常。未知 Reranker 程序错误、VectorStore 数据契约损坏等仍然抛出，避免把代码缺陷伪装成正常降级。

### 聊天历史窗口

Router、Rewrite 和 Direct Answer 全部调用同一个 `bounded_chat_history()`：

- 最多保留最近 6 条有效 user/assistant 消息；
- 总正文最多 4000 字符；
- 忽略非法 role、非字符串和空内容；
- 不保存长期记忆。

Direct Answer 会把裁剪后的多轮历史置于 system prompt 与当前问题之间，仍不读取或触发检索上下文。

### 安全边界

公开失败状态从固定映射生成，不包含 `str(exception)`、API key、完整 prompt、请求头、候选正文或文档内容。测试使用带 secret 的异常验证序列化后的 failure 对象不泄漏原始信息。

## Verification

专项测试：

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q `
  tests/test_workflow_failure_contract.py `
  tests/test_agent_graph.py `
  tests/test_retrieval_pipeline.py
```

结果：`52 passed in 4.80s`

语法编译与全量回归：

```powershell
cd backend
.\.venv\Scripts\python.exe -m compileall -q src tests
.\.venv\Scripts\python.exe -m pytest -q
```

结果：`374 passed, 1 skipped in 32.66s`。跳过项仍是原有显式 opt-in 的外部 LLM smoke test；新增测试均为离线确定性测试。

## Remaining Issues

- 本任务未接入 FastAPI、SSE 或 Langfuse SDK；结构化状态已可由这些后续消费者直接序列化。
- 未实现自动重试、熔断、异步检索或长期记忆。
- Context fatal 使用当前组件公开的 `ContextBuilderError` 契约；未知编程错误不会被静默吞掉。
- 固定安全错误文案是工程占位文案，最终用户级措辞按任务范围留待后续确定。
