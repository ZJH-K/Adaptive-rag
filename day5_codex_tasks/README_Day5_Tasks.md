# Adaptive RAG Day 5 · Codex 任务清单

## 说明

技术文档的 Day 5 目标是 **Rerank 与 Langfuse**。Day4 审查结论为 `PASS WITH ISSUES`，因此本任务包先关闭会影响 Day5 的运行时基础问题，再实现 Reranker、失败语义和全链路追踪。

本任务包把 Day5 拆为 6 个适量、可单独交给 Codex 的任务。

## 推荐执行顺序

| 顺序 | 任务 | 依赖 | 核心产出 |
|---|---|---|---|
| 1 | D5-01 运行时装配与诊断修复 | Day4 | BM25 启动恢复、请求级 diagnostics、Top-N 权威配置 |
| 2 | D5-02 Reranker Client/Adapter | Day4 SearchHit | 独立可测试的重排组件 |
| 3 | D5-03 Rerank Pipeline 集成 | D5-01、D5-02 | 过召回、Top-K、失败回退、Context 接入 |
| 4 | D5-04 工作流失败语义 | D5-03 | Router/Rewrite/Retrieval/Rerank/Generation 的统一错误契约 |
| 5 | D5-05 Langfuse 全链路 Trace | D5-01、D5-03、D5-04 | 请求级 Trace、span、脱敏、No-op 降级 |
| 6 | D5-06 集成验收与真实 Smoke | 全部 | 全量测试、覆盖率、小样本对比、验收报告 |

## 单次任务使用方式

每次只把一个任务文档交给 Codex，并同时确保 Codex 可访问：

- 仓库代码；
- 根目录 `AGENTS.md`；
- `adaptive_rag_project_technical_spec.md`；
- `Day4_Review_Report.md`。

建议每个任务使用独立提交，提交信息示例：

```text
feat(day5): harden retrieval runtime
feat(day5): add reranker adapter
feat(day5): integrate rerank pipeline
fix(day5): define workflow failure contract
feat(day5): add langfuse tracing
test(day5): add acceptance and smoke evidence
```

## Day5 完成判定

只有同时满足以下条件，Day5 才可判定完成：

1. RRF 候选可被 Reranker 重新排序；
2. Reranker 失败时回退且不阻断基础回答；
3. 重排后引用来源与 ContextBuilder 实际使用 Chunk 一致；
4. Langfuse Trace 覆盖 Router、Rewrite、Retrieval、Rerank、Generation；
5. Trace 数据来自请求局部状态，不存在串线；
6. 持久化 Chroma 重启后首次查询即可使用 BM25；
7. `retrieve_top_n` 和 `rerank_top_k` 真实生效；
8. 外部服务 Smoke 结果被诚实记录；
9. 全量测试无回归；
10. 未提前实现 Day6/Day7 范围。

## 范围控制

Day5 不应实现：

- FastAPI 路由；
- SSE；
- Streamlit；
- Docker Compose；
- 20–30 条正式 Evaluation；
- 最终 README 包装；
- Langfuse 自部署。
