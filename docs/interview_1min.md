# 一分钟面试讲解

这是一个以 RAG 为核心的技术文档问答项目，不是通用 Agent。用户可以上传 PDF 或
Markdown；系统保留页码和标题层级，使用递归、Markdown heading 和 PDF page-aware
三种切分策略。问答请求统一进入 LangGraph，Router 判断是否需要文档；需要时先做
Query Rewrite，再执行 Chroma Dense 与 BM25 召回、RRF 融合和可选 Rerank，最后由
ContextBuilder 同时生成上下文和可核验 Sources，通过 FastAPI SSE 流式返回。

工程上我处理了 Provider 降级、Request/Trace 生命周期和浏览器断连取消，并用 Docker
Compose 固定单 worker 保证 Chroma/BM25 一致性。为了验证而不是宣传优化，我构建了
24 条人工证据数据集和 A/B/C/D Runner。正式结果中 A/B/C 完成、D 因当次未配置
Reranker 跳过；结构化切分和 Hybrid 在这个小样本上没有超过 Baseline，这暴露了下一步
需要扩充语料和调参的问题。真实 Reranker 与 Langfuse Smoke 目前也明确标记 NOT RUN。
