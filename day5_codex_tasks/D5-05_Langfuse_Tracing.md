# Adaptive RAG · Day 5 Codex 任务

> 阶段：Day 5 — Rerank 与 Langfuse  
> 协作方式：Codex 负责编码与自测，人工负责 Review 与验收  
> 基线：Day 4 已完成 Hybrid Retrieval，但审查结论为 **PASS WITH ISSUES**

## 必读材料

开始编码前必须阅读：

1. `adaptive_rag_project_technical_spec.md`
2. `Day4_Review_Report.md`
3. 仓库根目录 `AGENTS.md`
4. 与本任务相关的现有实现和测试

若文档与当前代码不一致：

- 先以当前代码的公开契约和已有测试为事实基线；
- 不得静默改写公共接口；
- 在交付报告中记录差异、选择和理由；
- 涉及契约变更时，必须同步修改测试和调用方。

## 任务编号

`D5-05`

## 任务名称

接入 Langfuse 全链路 Trace

## 目标

为一次完整问答请求生成一个 Langfuse Trace，覆盖：

```text
router
query_rewrite
dense_retrieval
bm25_retrieval
rrf_fusion
rerank
context_build
final_answer
```

Trace 必须绑定当前请求的真实数据，不能读取共享 `last_diagnostics`，并能记录成功、降级和失败状态。

## 上下文

技术规格要求记录 Router、Rewrite、Retrieval、Rerank、Generation 的输入输出、耗时、Chunk ID 和各阶段分数。Day4 Review 特别指出，共享可变 diagnostics 会把 B 请求的数据记录到 A 请求 Trace，因此本任务必须建立请求级 Trace Context。

Langfuse 自部署不是 Day5 必需项；优先兼容 Langfuse Cloud 或可注入的 SDK Client。

## 范围

### 必须完成

1. 建立可替换的 observability 抽象：
   - 业务代码不应散落 Langfuse SDK 细节；
   - 支持真实 Langfuse 实现和 No-op/Fake 实现；
   - Langfuse 未配置或临时失败时，核心问答不应因此失败。

2. 请求级 Trace 生命周期：
   - 创建 trace；
   - 将 trace_id 写入 AgentState/运行结果；
   - 节点或阶段创建 generation/span；
   - 正常结束、降级、致命错误均正确关闭。

3. 至少记录以下安全字段：
   - question；
   - need_retrieval；
   - route_reason；
   - rewritten_query；
   - retrieved_chunk_ids；
   - context_chunk_ids；
   - dense_score；
   - bm25_score；
   - fused_score；
   - rerank_score；
   - dense/bm25/fused/rerank 数量；
   - 各阶段 latency；
   - degraded/fallback 信息；
   - answer；
   - sources。

4. 敏感信息处理：
   - 不记录 API key；
   - 不记录请求头；
   - 文档正文默认只记录截断摘要或关闭；
   - 可通过配置控制是否记录完整 question/answer；
   - 错误堆栈只在安全范围内记录。

5. 与 LangGraph 集成：
   - Direct 分支只出现 router + direct_answer；
   - RAG 分支阶段顺序与实际执行一致；
   - 降级时 span 状态和 metadata 正确；
   - Trace ID 可供 Day6 返回，但本任务不实现 SSE。

6. 增加配置和 `.env.example`。

### 可修改区域

- `backend/src/observability/`
- `backend/src/agent/`
- `backend/src/rag/retrieval/`
- `backend/src/config.py`
- `.env.example`
- 对应测试

### 不在范围

- Langfuse 自部署；
- Docker Compose；
- FastAPI/SSE；
- Streamlit；
- Dashboard 截图自动化；
- OpenTelemetry 全面接入。

## 约束

1. Langfuse 不得成为核心业务的硬依赖。
2. 默认测试必须使用 Fake/No-op，不访问网络。
3. 不从共享实例字段读取当前请求诊断。
4. Trace 数据必须来自实际运行结果。
5. 不记录模型思维链。
6. 不把完整候选文档默认上传到观测平台。
7. SDK 版本差异应封装在 Adapter 内。
8. 所有 span/generation 必须在异常路径正确结束。

## 验证方式

至少覆盖：

1. Direct 分支 Trace 拓扑；
2. RAG 分支完整 Trace 拓扑；
3. Reranker 禁用；
4. Reranker 成功；
5. Reranker 失败降级；
6. Dense/BM25 单路降级；
7. Generation fatal；
8. Trace ID 写入状态；
9. 分数和 Chunk ID 与真实结果一致；
10. 两个交错请求的 Trace 数据不串线；
11. Langfuse 未配置时 No-op；
12. Langfuse SDK 抛错时问答仍按既定失败契约运行；
13. 敏感字段不被记录；
14. span 在异常路径关闭；
15. 全量测试无回归。

可提供 opt-in 真实 Smoke Test，但默认跳过。

## 最终交付

1. Langfuse Adapter 与 No-op/Fake 实现；
2. 全链路 Trace 集成；
3. 配置与示例环境变量；
4. 自动化测试；
5. `docs/day5_task05_langfuse_report.md`，包含：
   - Trace 树；
   - 字段清单；
   - 脱敏策略；
   - 降级行为；
   - Fake 测试证据；
   - 真实 Smoke 的执行方式；
6. 若执行真实 Smoke，保存脱敏后的 trace_id 或截图路径说明。
