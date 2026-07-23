# Adaptive RAG Day 7：Codex 任务索引

## Day 7 总目标

把当前“功能可运行”的项目提升为“可量化评估、可复现部署、可用于简历和面试展示”的完整交付，同时先关闭 Day6 审查中会影响最终结论可信度的发布阻塞项。

本任务包依据：

- `adaptive_rag_project_technical_spec.md` 中 Day 7、Evaluation、Docker、README、最终交付要求；
- `Day6_Review_Report.md` 中 M1–M4、Day7 Impact 和 Recommendation；
- 当前项目已有 Day1–Day6 实现，不要求重写已通过的 Parser、Chunker、Hybrid Retrieval、Reranker、FastAPI 或 Streamlit 主体。

## 推荐执行顺序

| 顺序 | 任务 | 目的 | 前置依赖 |
|---|---|---|---|
| 1 | Task 01：统一 LangGraph 与 SSE 生产编排 | 消除 Demo 与 Evaluation 的双重工作流真相 | Day6 当前代码 |
| 2 | Task 02：加固 Request ID 与 Trace 生命周期 | 修复并发串线和状态无界增长 | Task 01 可并行，但建议先完成 |
| 3 | Task 03：异步 SSE 取消与资源释放 | 证明浏览器断连会停止上游流并正确收尾 | Task 01、Task 02 |
| 4 | Task 04：构建正式 Evaluation 数据集 | 建立 20–30 条真实、可追溯评估样本 | Task 01，知识库稳定 |
| 5 | Task 05：实现 Evaluation 指标库 | 提供可独立验证的指标计算能力 | Task 04 schema 确定 |
| 6 | Task 06：实现 A/B/C/D 实验 Runner 与报告 | 自动运行四组实验并输出真实报告 | Task 04、Task 05 |
| 7 | Task 07：Docker 与 Compose 部署 | 固定 Python 3.11、单 worker 和依赖装配 | Task 01–03，运行时稳定 |
| 8 | Task 08：README、架构、NOTICE 与展示材料 | 完成最终项目包装和验收证据 | Task 06、Task 07 |

## 任务边界

### 必须完成

1. 生产 Demo 与 Evaluation 使用同一套权威编排逻辑；
2. 内部 Request ID 服务端唯一，Trace 状态有明确回收；
3. 异步 Provider 流和 HTTP 断连取消路径有自动化测试；
4. Evaluation 数据集不少于 20 条；
5. Hit Rate@K、Recall@K、MRR、关键词答案正确性可自动计算；
6. A/B/C/D 四组实验可通过统一命令执行；
7. Docker Compose 至少启动 backend 与 frontend；
8. README、架构图、指标结果和 AnyKB 复用声明完整。

### 不在 Day 7 扩展

- 多用户、权限、多租户；
- 多 Agent；
- OCR、复杂 PDF 表格恢复；
- Web Search、MCP；
- Redis/Kafka/Celery；
- Kubernetes；
- 多 worker 下的跨进程 BM25 一致性；
- Langfuse 自部署集群；
- 为了“跑出更好指标”而修改问题、标签或人工伪造分数。

## 全局约束

- 每个任务开始前先阅读仓库根目录 `AGENTS.md`、技术文档、Day6 审查报告及相关现有测试。
- 保留现有统一数据模型：`Chunk`、`SearchHit`、`RetrievalResult`、ContextBuilder 来源映射。
- 不得把 Fake、人工排序或未运行的外部 Smoke 写成真实效果结论。
- 没有外部凭据时，真实 LLM/Reranker/Langfuse 结果必须标记为 `NOT RUN` 或 `SKIPPED`，不能生成示例数字冒充结果。
- 修改必须带测试；完成单任务后运行专项测试，再运行后端全量测试；涉及前端时同时运行前端测试。
- 每个任务只提交与本任务相关的文件，禁止顺手重构无关模块。
- 所有错误消息、日志、报告和提交产物不得包含 API Key、Authorization Header 或原始敏感配置。

## 每个 Codex 任务的统一回报格式

Codex 完成任务后应返回：

1. Changed Files；
2. Implementation Summary；
3. Validation Commands；
4. Validation Results；
5. Known Limitations / NOT RUN；
6. 是否满足本任务“最终交付”。

## Day 7 总体验收门槛

```text
后端全量 pytest 通过
前端全量 pytest 通过
四组 Evaluation Runner 可执行
Evaluation 报告包含配置快照和真实运行状态
docker compose config 通过
docker compose up --build 可启动前后端
README 中的架构与生产代码实际执行路径一致
README 不夸大未执行的真实 Reranker/Langfuse 能力
```
