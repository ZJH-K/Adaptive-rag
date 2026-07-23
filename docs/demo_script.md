# 2–3 分钟 Demo 演示脚本

目标时长约 2 分 40 秒。录制前按 `demo_checklist.md` 完成预热，不在镜头中展示
`.env`、Authorization、完整 Request/Trace ID 或 Provider Dashboard 敏感字段。

## 0:00–0:20 项目定位

打开 README 架构图并说明：这是技术文档 RAG，而不是通用 Agent。LangGraph 只做
“直接回答 / 进入 RAG”的路由；核心是结构化入库、Hybrid Retrieval、Sources 和
Evaluation。

## 0:20–0:50 上传与入库

打开 Streamlit，上传 `knowledge/markdown/langgraph_checkpoint.md`，选择
`markdown_heading`。指出完成状态、文档数和 Chunk 数。若演示 PDF，再上传
`knowledge/pdf/dense_retrieval_guide.pdf` 并选择 `pdf_page_aware`，强调页码保留。

## 0:50–1:40 自适应问答

提问：

> 文档里说的它需要哪个会话标识符，配置持久状态时按什么步骤操作？

展示并口述：

1. Router 选择检索分支；
2. Rewrite 把指代补全为独立查询；
3. Retrieval 面板显示 Dense、BM25、RRF 的实际计数；
4. 回答以 SSE 增量出现；
5. Sources 显示 Markdown 章节或 PDF 页码。

若 `health.reranker.available=true` 且本次 retrieval 明确
`rerank_entered=true`，才展示真实 Reranker；否则直接说明“适配器和降级契约已完成，
真实 Smoke 尚未作为提交证据”，不要口述重排收益。

## 1:40–2:05 直接回答与取消

提问一个不依赖文档的通用问题，展示 Router 选择 direct，说明该分支不执行
Retrieval。可简短说明浏览器关闭连接时，取消会传递到 LangGraph 和 Provider iterator，
避免后台继续生成；录制中不必故意制造不稳定断连。

## 2:05–2:30 Evaluation

打开 `evaluation/reports/day7-task06-run/report.md`：24 条人工证据标注，A/B/C 已完成，
D 跳过。指出 A→B 的 Hit@1/Recall@1 下降、B→C 延迟上升；结论是当前小语料没有
证明优化收益，Evaluation 的价值是发现退化，而不是包装结果。

## 2:30–2:40 Trace 与收尾

只有 SSE `done.trace_exported=true` 且已有脱敏 Dashboard 截图时才展示 Langfuse。
当前默认口述：“Observer、状态语义和离线契约已完成，真实 Langfuse 导出证据 TODO。”
最后回到架构图，强调 Docker 可复现、单 worker 限制和可降级外部能力。

## 录制后

按 `docs/evidence/README.md` 命名截图/日志，确认视频中没有密钥、Cookie、完整 Trace
URL、个人账号或未脱敏问题文本，再把实际视频链接补到根 README。
