# Adaptive RAG：Day 4 Codex 任务包

## 1. 任务包目的

本任务包用于把 Day 4「Hybrid Retrieval」拆分为可独立交给 Codex 执行、由人工逐项 Review 和验收的单次任务。

拆分依据：

- 技术文档中 Day 4 的目标：`Chroma Dense + BM25 + RRF Fusion`；
- Day 3 审查结论：进入 Day 4 前，应先修复真实结构化输出契约和 ContextBuilder 精确来源映射；
- 当前架构已有统一 `SearchHit` 和 `Retriever` Protocol，Day 4 应在不让 Agent 感知 Dense/BM25 细节的前提下替换检索实现；
- Day 4 不提前实现 Reranker、Langfuse、FastAPI、SSE、Streamlit 或 Evaluation 完整框架。

## 2. 执行顺序

| 顺序 | 任务 | 性质 | 前置依赖 |
|---:|---|---|---|
| 1 | D4-01 精确来源映射闭环 | Day 3 阻塞修复 | Day 3 当前代码 |
| 2 | D4-02 Router/Rewrite 结构化输出闭环 | Day 3 阻塞修复 | Day 3 当前代码 |
| 3 | D4-03 中文 Tokenizer 与 BM25 索引 | Day 4 基础设施 | D4-01、D4-02 已合并 |
| 4 | D4-04 BM25 Retriever | Day 4 核心功能 | D4-03 |
| 5 | D4-05 RRF Fusion | Day 4 核心算法 | D4-04 |
| 6 | D4-06 Hybrid Retrieval Pipeline 集成 | Day 4 系统集成 | D4-04、D4-05 |
| 7 | D4-07 测试、对比实验与验收报告 | Day 4 验收闭环 | D4-06 |

必须按顺序执行。每个任务完成并 Review 通过后，再把下一份 Markdown 交给 Codex。

## 3. 每次交给 Codex 的材料

最低材料：

1. 当前任务 Markdown；
2. 仓库根目录 `AGENTS.md`；
3. 当前最新代码仓库；
4. `adaptive_rag_project_technical_spec.md`。

执行 D4-01、D4-02 时还必须提供 `Day3_Review_Report.md`。后续任务也建议保留该报告，便于避免来源映射和工作流边界回归。

## 4. 统一执行规则

- Codex 开始前先阅读 `AGENTS.md`、技术文档、当前任务和相关现有实现；
- 先检查仓库当前状态，不假设文件名、类名或接口与任务文档完全一致；
- 只修改当前任务所需范围，不顺手重构无关模块；
- 新代码应延续当前的类型标注、依赖注入、Pydantic 模型和 pytest 风格；
- 所有外部服务测试默认使用 Fake/Stub，不允许单元测试依赖真实网络；
- 涉及真实 DeepSeek/Embedding 的 Smoke Test 必须可显式开启，默认跳过；
- 不删除或弱化已有 Day 1–Day 3 测试；
- 每项任务结束时必须给出：改动摘要、文件清单、测试命令、测试结果、已知限制、未完成项；
- 若发现任务要求与仓库现状冲突，优先保持现有稳定接口，并在交付说明中记录差异和理由，不得静默改动架构。

## 5. Day 4 完成定义

完成全部 7 项任务后，至少满足：

- ContextBuilder 的实际来源映射在工作流状态中可追踪，citation ID 不会因去重或截断错位；
- Router/Rewrite 的结构化输出有明确调用契约、严格解析和可复现验证；
- 中文 Tokenizer 可测试，BM25 索引能由现有 Chunk 构建；
- BM25 Retriever 返回统一 `SearchHit`；
- Dense 与 BM25 可通过 RRF 稳定融合；
- 任一路为空时 Hybrid Retrieval 仍能返回另一条路径结果；
- Dense、BM25、Fused 分数均被正确保留；
- LangGraph 仍只依赖统一 Retriever 接口，不感知具体检索策略；
- 至少有 3 个关键词型案例证明 Hybrid 优于 Dense；
- 全量测试无回归，并产出 Day 4 验收报告。

## 6. 范围边界

Day 4 允许：

- `jieba` 或项目内可替换的中文分词实现；
- `rank_bm25`；
- BM25 内存索引或与当前持久化方式兼容的轻量索引；
- RRF 参数配置；
- Dense-only / Hybrid 配置开关；
- 为后续 Day 5 保留清晰扩展点。

Day 4 禁止提前实现：

- BGE Reranker；
- Langfuse Trace；
- FastAPI 路由；
- SSE；
- Streamlit；
- Docker Compose 完善；
- 完整 Day 7 Evaluation 框架；
- Elasticsearch、Milvus、Redis、PostgreSQL 等超出 MVP 的基础设施。
