# Demo Evidence Policy

本目录只保存真实运行产生并完成脱敏的证据。禁止创建“示例截图”冒充 Streamlit、
Reranker 或 Langfuse 真实结果。

## 当前状态（2026-07-23）

| 证据 | 状态 | 说明 |
|---|---|---|
| Streamlit 主链路截图/GIF | TODO | 需人工录制 |
| 上传 Markdown/PDF 截图 | TODO | 需人工录制 |
| 真实 Reranker Smoke | NOT RUN | Task 06 D 为 `reranker_not_configured` |
| Langfuse Dashboard Trace | NOT RUN | 无真实导出截图 |
| 正式 Evaluation | AVAILABLE | 引用 `evaluation/reports/day7-task06-run/` |
| Docker 启动/重启/持久化 | AVAILABLE | 引用 `docs/day7_task07_acceptance.md` |

## 文件命名

```text
streamlit-upload-markdown-YYYYMMDD.png
streamlit-upload-pdf-YYYYMMDD.png
streamlit-rag-flow-YYYYMMDD.png
streamlit-sources-page-section-YYYYMMDD.png
demo-adaptive-rag-YYYYMMDD.mp4
reranker-smoke-YYYYMMDD.json
langfuse-trace-redacted-YYYYMMDD.png
docker-smoke-YYYYMMDD.txt
```

同一天的重录使用 `-02`、`-03` 后缀。不要把 Request ID、Trace ID 或用户问题放进
文件名。

## 脱敏要求

- 删除 API key、Authorization、Cookie、Session、账号、邮箱、余额和内部主机名；
- Request ID 如必须展示，只保留前后各 4 位；Trace ID 与 Dashboard URL 默认遮蔽；
- 问题/答案默认视为可能敏感，公开前进行人工审阅；
- 日志只保留状态码、能力状态、计数和耗时，不保留 Provider 原始响应体；
- 不提交 `.env`、HAR、浏览器 Profile、Chroma 本地数据或未脱敏终端转储。

## 真实性要求

截图必须来自与当前提交对应的实际运行。Reranker 证据必须同时包含 health 的
available 状态和 retrieval 的 `rerank_entered=true`；Langfuse 证据必须能对应
SSE `done.trace_exported=true`。离线 Fake、手工 JSON 和 Evaluation 的其他组结果
不能替代这些外部证据。
