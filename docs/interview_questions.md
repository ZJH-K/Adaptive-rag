# Adaptive RAG 面试问题与回答要点

## 1. 为什么 Agent 只做 Router？

项目目标是证明 RAG Pipeline，而不是展示自治工具调用。Router 只在 direct 与 retrieve
间选择，使两条路径、失败边界和 Evaluation 都可解释；复杂 Agent 会引入工具选择、
记忆和权限等无法在一周内充分验证的变量。

## 2. 为什么 Dense Retrieval 不够？

Dense 擅长语义相似，但技术文档常含 `thread_id`、错误码、模型名和 API 标识符。BM25
对精确词项更敏感，两者具有互补潜力。不过潜力不等于收益：正式 C 组没有超过 B，
说明仍需调 Top-N、分词、语料和查询类型。

## 3. 为什么使用 RRF？

Dense similarity 与 BM25 score 的尺度和分布不同，直接加权需要归一化与调参。RRF 只按
各列表排名计算 `Σ1/(k+rank)`，实现简单且对分数尺度不敏感。代价是它忽略原始分数差距，
仍需通过 Evaluation 调 `k` 和候选深度。

## 4. 为什么先召回再 Rerank？

Cross-Encoder 类 Reranker 对 query-document pair 逐个评分，直接扫全库成本过高。Dense
和 BM25 先追求 Recall，RRF 产生有限 candidates，再用 Reranker 提升排序精度。当前项目
只有 Adapter/降级契约，D 组跳过，不能声称真实收益。

## 5. Chunk A/B 如何公平比较？

A/B 使用相同 5 份知识文件、Embedding/LLM、chunk size=800、overlap=100、Top-N 和
Evaluation 问题；差异只在切分策略。人工 evidence 分别解析到 recursive 与 optimized
稳定 Chunk ID，避免用某一策略的 ID 评价另一策略，也不从检索结果反推标签。

## 6. 为什么结构化 Chunk 反而可能变差？

保留结构不保证当前 embedding 能更好排序。标题边界可能把 Baseline 中恰好共现的内容
拆开，相关集合数量也可能变化。当前 A→B Hit@1、Recall@1 和 MRR 均下降，需要从 q015、
q019 等失败样本检查边界、标题文本注入和 chunk size，而不是删除失败样本。

## 7. Reranker 或 Langfuse 失败如何降级？

Reranker 失败时保留 RRF candidate order，标记 degraded 和错误码，不中断回答。Langfuse
是 telemetry：配置不完整或 SDK/Provider 失败时使用 No-op，不影响业务；只有真实 trace
创建才给 trace ID，只有终态 flush 成功才给 `trace_exported=true`。

## 8. 为什么 Docker 固定单 worker？

Chroma 是持久化事实源，但 BM25 是每进程内存索引，入库锁也只覆盖单进程。多 worker
会产生不同 generation 和更新竞态。当前选择显式固定一个 worker，未来应使用外部全文
检索/协调机制后再横向扩展。

## 9. SSE 断连如何取消 Provider？

路由层监听 ASGI `http.disconnect`，并与 `anext(service stream)` 竞速。断开后取消待处理
任务，LangGraph async generation 收到 cancellation，Provider async iterator 在 finally
中 `aclose`，Observer 以 cancelled 终结。AnyIO shield 只保护清理，不吞掉取消信号。

## 10. Request ID 和 Trace ID 为什么分开？

内部 request ID 每个 HTTP 请求唯一，是资源生命周期键；调用方 `X-Request-ID` 可能重复，
只作为 client correlation。Trace ID 属于外部 Provider，可能不存在或创建失败。分离可避免
并发请求串 Trace，也避免 No-op 模式伪造 Trace ID。

## 11. Context 和 Sources 如何避免错配？

ContextBuilder 在预算裁剪时同时构造 Context、按序 chunk IDs 和 Sources。Generation 与
SSE 都消费同一图 state；SSE 不从原始 retrieval hits 重建引用，所以被预算移除的候选
不会出现在 Sources 中。

## 12. Evaluation 为什么可信？

问题与 evidence 由人工维护；Resolver 只按 quote + page/heading_path 映射生产 Chunk ID，
Validator 检查来源和策略 ID。Runner 为每组创建独立索引，记录 dataset/knowledge/lock
哈希、模型名、代码版本和状态。局限是只有 24 条项目内样本，不能代表生产分布。

## 13. AnyKB 复用了什么、重写了什么？

参考了 Parser 职责/最小清洗思想、递归 Chunk 的段落→句子→字符层级和模块拆分思路。
本项目的 schema、稳定 ID、PDF/Markdown 结构保留、Embedding、Chroma/BM25/RRF、
Reranker Adapter、LangGraph/SSE、Evaluation 和部署均独立实现；未迁入多租户、权限、
复杂 Agent、记忆、Next.js 或数据库栈。复制任何上游源码前仍需核验 LICENSE。

## 14. 当前最重要的下一步是什么？

先扩充并分层 Evaluation，分析失败样本、调 Chunk/Top-N/RRF，然后以真实 Reranker 补 D
组；同时增加引用完整率和忠实度人工复核。功能扩张优先级低于证明检索质量与一致性。
