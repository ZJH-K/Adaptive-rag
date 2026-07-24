# Adaptive RAG Day6 Codex 任务包

## 1. 本任务包目标

Day6 的原始目标是完成：

```text
FastAPI + 文档接口 + SSE 流式问答 + Streamlit
→ 形成可从浏览器操作的端到端 Demo
```

但 Day5 审查报告给出的结论是 **PASS WITH ISSUES**，并明确指出以下问题会直接影响 Day6：

1. BM25/Chroma 真实故障尚未形成完整的类型化失败与单路降级契约；
2. 并发入库可能让较旧 BM25 快照覆盖较新快照，`needs_rebuild` 未被查询路径消费；
3. Langfuse 尚未形成可信的请求根 Trace、导出状态和真实业务时长语义；
4. API 必须区分本地 `request_id`、Langfuse `trace_id`、`tracing_enabled` 和 `trace_exported`；
5. Day6 SSE 不能只把同步 `graph.invoke()` 包装成流式响应，必须实现真正的最终答案 token 流。

因此本任务包将 Day6 拆成 7 个单次任务，其中 D6-01～D6-03 是进入 API/UI 开发前的验收门槛。

## 2. 执行顺序

| 顺序 | 文件 | 任务 | 前置依赖 |
|---|---|---|---|
| 1 | `D6-01_retrieval_failure_contract.md` | 检索失败类型化与单路降级 | Day5 当前代码 |
| 2 | `D6-02_ingestion_consistency.md` | 并发入库与 BM25 一致性 | D6-01 |
| 3 | `D6-03_observability_readiness.md` | Langfuse 生命周期、导出状态与外部 Smoke | D6-01 |
| 4 | `D6-04_fastapi_foundation_health.md` | FastAPI 应用基座、生命周期与健康检查 | D6-01～D6-03 |
| 5 | `D6-05_documents_api.md` | 上传、加载内置知识库与统计接口 | D6-02、D6-04 |
| 6 | `D6-06_chat_sse.md` | 真正 token 流式的聊天 SSE 接口 | D6-01、D6-03、D6-04 |
| 7 | `D6-07_streamlit_e2e.md` | Streamlit UI、API 客户端与 Day6 端到端验收 | D6-05、D6-06 |

必须按顺序执行。不要让 Codex 在同一个任务中提前实现后续任务内容。

## 3. 每次交给 Codex 的共同上下文

开始任务前，要求 Codex 阅读：

1. 仓库根目录的 `AGENTS.md`；
2. `adaptive_rag_project_technical_spec.md` 中第 13、14、16、19、20、21 节；
3. `Day5_Review_Report.md`；
4. 仓库现有 `docs/day5_acceptance_report.md`；
5. 当前任务明确列出的相关源文件与测试。

如果技术文档或审查报告不在仓库中，应在 Codex 会话中作为附件提供；不要让 Codex凭记忆补写需求。

## 4. 全局约束

- 保持项目主体是 RAG，不增加多 Agent、权限系统、多租户、会话持久化、任务队列或复杂前端。
- 不提前实现 Day7 Evaluation、Docker、README 全量包装。
- 保留现有 `SearchHit`、`RetrievalResult`、ContextBuilder 精确来源映射和 LangGraph 两分支语义。
- 不通过 `except Exception: pass`、伪造 Trace ID、把整段答案切字符串等方式“完成”验收。
- 外部服务凭据缺失时必须诚实标记 `NOT RUN` / `unavailable`，不得伪造真实 Reranker 或 Langfuse 成功证据。
- 新增公共契约必须有类型定义和测试；API/SSE 返回不得包含 Prompt、API Key、原始异常栈或模型私有思维链。
- 每个任务完成后先运行专项测试，再运行全量测试；不得以“理论上通过”代替实际命令结果。

## 5. Day6 最终验收主链路

```text
启动 FastAPI
→ 启动时构建唯一 Retrieval Runtime，并恢复 BM25
→ 浏览器上传 PDF/Markdown
→ Chroma 写入完成且 BM25 使用最新快照
→ 立即发起问题
→ Router / Rewrite / Retrieval / Rerank 过程通过 SSE 输出
→ DeepSeek 最终答案真实 token 流式输出
→ Sources 严格使用 ContextBuilder 的实际来源映射
→ Streamlit 展示回答、来源、检索过程和可验证的 Trace 状态
```

## 6. 建议的 Review 节点

- 完成 D6-03 后：做一次“Day5 遗留问题关闭”专项 review；
- 完成 D6-06 后：重点 review SSE 事件顺序、断连取消和错误收口；
- 完成 D6-07 后：执行 Day6 整体验收，不要只看截图。
