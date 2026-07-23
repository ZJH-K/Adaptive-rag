# 三分钟面试讲解

## 1. 定位

项目解决的是技术文档问答。Agent 能力被刻意压缩：LangGraph 只决定直接回答还是进入
RAG，并编排 Rewrite、Retrieval 和 Generation；没有工具自治循环、多 Agent 或 Web
Search。这样主要复杂度集中在能被测试和评估的 RAG 工程。

## 2. 入库设计

PDF Parser 保留一基页码，Markdown Parser 保留 heading path。除了递归 Baseline，
Markdown 在标题边界内合并，PDF 按页切分；Chunk ID 来自稳定内容与元数据。Embedding
批量写入 Chroma 后才发布新的 BM25 generation，避免向量与词法索引部分成功。

## 3. 检索与回答

检索问题先由 LLM 改写成独立查询。Dense 负责语义召回，BM25 补充标识符和关键词，
RRF 只使用排名，避免直接混合不同分数尺度。Reranker 是可选阶段，失败就保留 RRF
顺序并输出 degradation code。ContextBuilder 同时生成 Context、chunk IDs 和 Sources，
所以答案 `[S1]` 与页面/章节不会由 SSE 层二次猜测。

## 4. 流式与可观测性

浏览器主链路只使用 lifespan 创建的一份 compiled LangGraph。Provider 的 async token
通过 custom events 一对一进入 SSE。客户端断开时取消会传播到图和 Provider iterator，
随后用 cancelled outcome 释放 Trace。内部 request ID 每请求唯一，客户端 ID 只做关联；
Trace ID 只有 Provider 真正创建才存在，flush 成功才标记 exported。

## 5. Evaluation 与诚实结论

数据集有 24 条人工证据标注问题、5 份知识文件和 6 类问题，相关 Chunk ID 由证据定位
到生产 Parser/Chunker，不从 Top-K 反推。A 是 Recursive + Dense，B 是结构切分 + Dense，
C 加 Hybrid + RRF，D 再加 Rerank。正式运行中 A/B/C 完成，D 跳过。A→B Hit@1 从
0.9167 降到 0.8333，Recall@1 从 0.8056 降到 0.7014；B→C 延迟增加约 139.5 ms，
MRR 也略降。因此当前结果没有证明优化收益，但 Runner 成功发现了退化并保留复现配置。

## 6. 部署与边界

后端和前端是非 root Python 3.11 镜像。Compose 持久化 Chroma、只读挂载知识库，
并固定一个 Uvicorn worker，因为进程内 BM25 和入库锁还不支持多进程一致性。真实
Reranker/Langfuse Smoke 尚无证据；下一步是扩大数据集、调参、补 D 组和引用忠实度评审，
而不是先扩展成复杂 Agent 平台。
