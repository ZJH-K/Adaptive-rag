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

`D5-03`

## 任务名称

将候选过召回与 Rerank 接入 Retrieval Pipeline

## 目标

把 Reranker 插入到正确位置：

```text
Dense + BM25
→ RRF Fusion
→ Rerank
→ Context Builder
```

实现默认 `retrieve_top_n=20`、`rerank_top_k=5`，并确保 Reranker 失败时回退到 RRF 顺序且问答链路不中断。

## 上下文

Day4 的 Hybrid Pipeline 已能输出统一 SearchHit。Day5 技术规格要求：

- 先过召回；
- RRF Top 20 进入 Cross-Encoder；
- 取重排后的 Top 5；
- Reranker 失败时保留 RRF 顺序；
- ContextBuilder 和引用来源必须基于实际重排后、实际使用的候选。

Day4 Review 同时要求候选数量配置真实控制底层 Retriever，而不是只做结果切片。

## 范围

### 必须完成

1. 扩展 Retrieval Pipeline：
   - Dense-only 模式仍可工作；
   - Hybrid 模式先执行 RRF；
   - Reranker 启用时对候选池重排；
   - Reranker 禁用时返回 Fusion 顺序；
   - Reranker 失败时返回 Fusion 顺序；
   - 双路无结果时不调用 Reranker。

2. 配置语义：
   - `retrieve_top_n` 明确表示进入 Rerank 的候选池上限；
   - `rerank_top_k` 明确表示最终返回给 ContextBuilder 的上限；
   - 默认分别为 20 和 5；
   - 底层 Dense/BM25 实际召回数量必须足以形成候选池。

3. 返回请求级 diagnostics，至少包含：
   - retrieval mode；
   - dense_count；
   - bm25_count；
   - fused_count；
   - rerank_input_count；
   - rerank_output_count；
   - reranker_enabled；
   - reranker_degraded；
   - degraded_reason 的安全摘要；
   - 各阶段耗时。

4. 保护数据契约：
   - 重排后仍保留原始分数；
   - `rerank_score` 只在成功重排的候选上存在；
   - 降级时不伪造 `rerank_score`；
   - ContextBuilder 只消费最终候选列表；
   - `context_sources`、`context_chunk_ids` 与最终上下文严格一致。

5. 将新 Pipeline 注入现有 RAG Service/LangGraph，但 Agent 节点不得出现 Dense/BM25/RRF/Reranker 分支逻辑。

### 可修改区域

- `backend/src/rag/retrieval/pipeline.py`
- `backend/src/rag/context_builder.py`
- `backend/src/agent/nodes.py`
- `backend/src/agent/graph.py`
- 运行时装配模块
- 相关测试

### 不在范围

- Langfuse SDK 接入；
- FastAPI/SSE；
- Streamlit；
- 完整 Evaluation；
- 本地模型推理。

## 约束

1. Rerank 位于 Fusion 后、ContextBuilder 前。
2. 降级不得中断基础回答。
3. 降级不得静默：必须在请求级 diagnostics 中可观察。
4. 不得从原始 hits 重新推导 sources。
5. 不得改变 Direct 分支行为。
6. 不得把内部异常堆栈或密钥写入用户可见状态。
7. 保持离线测试确定性。

## 验证方式

至少覆盖：

1. Hybrid + Rerank 正常重排；
2. Dense-only + Rerank；
3. Reranker 禁用；
4. Reranker timeout/HTTP/解析失败时回退 RRF；
5. 一路为空仍可重排；
6. 双路为空不调用 Reranker；
7. retrieve_top_n 与 rerank_top_k 的真实语义；
8. 成功重排后 `rerank_score`、原始分数和 metadata 均正确；
9. 降级时没有伪造 `rerank_score`；
10. ContextBuilder 的 citation 与重排后顺序一致；
11. LangGraph Direct 分支零检索；
12. LangGraph RAG 分支顺序为 Rewrite → Retrieve/Rerank → Context → Generate；
13. 全量回归通过。

建议执行：

```bash
uv run pytest backend/tests/test_retrieval_pipeline.py -q
uv run pytest backend/tests/test_agent_graph.py -q
uv run pytest -q
```

## 最终交付

1. 完整 Pipeline 集成；
2. 请求级 diagnostics；
3. LangGraph/RAG Service 适配；
4. 新增测试；
5. `docs/day5_task03_rerank_pipeline_report.md`；
6. 一组确定性案例，展示 RRF 排名和 Rerank 后排名差异。
