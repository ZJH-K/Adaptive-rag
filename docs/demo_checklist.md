# Demo 录制前检查清单

## 环境与安全

- [ ] `.env` 已配置但不会出现在编辑器、终端历史或录屏窗口中。
- [ ] 关闭浏览器密码管理器、通知、个人书签和无关标签页。
- [ ] Provider Dashboard 只保留脱敏项目，隐藏账号、额度、完整 Trace ID 和 URL。
- [ ] `LANGFUSE_CAPTURE_QUESTION/ANSWER=false`，除非已获得展示内容授权。
- [ ] 不录制 `docker inspect`、环境变量转储或 HTTP Authorization Header。

## 服务

- [ ] `docker compose up --build -d --wait` 成功。
- [ ] `GET /api/live` 返回 `alive`。
- [ ] `GET /api/health` 返回可解析 JSON，并记录 LLM/Embedding/Reranker/Tracing 状态。
- [ ] Streamlit `http://127.0.0.1:8501` 可访问。
- [ ] 文档统计符合预期；需要干净演示时使用新的本地 `data/`，不要误删其他数据。

## 演示内容

- [ ] Markdown 上传使用 `markdown_heading`。
- [ ] PDF 上传使用 `pdf_page_aware`。
- [ ] 检索问题已预演，能稳定显示 Router、Rewrite、Dense/BM25/RRF、SSE 和 Sources。
- [ ] Direct 问题已预演且不会误入 Retrieval。
- [ ] Sources 至少包含一个 Markdown 章节或 PDF 页码。
- [ ] 正式报告路径是 `evaluation/reports/day7-task06-run/report.md`。

## 可选能力门槛

- [ ] 仅当 `reranker.available=true` 且 `rerank_entered=true` 时口述“真实执行”。
- [ ] 仅当 `done.trace_exported=true` 且 Dashboard 可核验时展示真实 Trace。
- [ ] 若门槛不满足，画面和讲稿明确写 `NOT RUN` / `TODO`，不使用旧截图替代。

## 录制后核验

- [ ] 时长 2–3 分钟，音画同步，关键文字可读。
- [ ] 视频、截图、日志命名符合 `docs/evidence/README.md`。
- [ ] 截图不是手工拼接的示例结果。
- [ ] Request ID 如需展示，仅保留前后各 4 位；Trace ID/URL 默认完全遮蔽。
- [ ] README 的视频/GIF 链接已指向真实文件或 URL，否则保持 TODO。
- [ ] `docker compose down` 后容器正常退出。
