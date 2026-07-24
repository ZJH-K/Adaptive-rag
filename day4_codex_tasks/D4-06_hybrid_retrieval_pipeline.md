# D4-06：集成 Hybrid Retrieval Pipeline 与配置开关

## 任务定位

本任务把现有 Dense Retriever、D4-04 BM25 Retriever 和 D4-05 RRF 组装成统一 Retrieval Pipeline，并通过现有 Retriever Protocol 接入 LangGraph。目标是完成 Day 4 的运行链路，但不负责最终三案例对比报告。

## 目标

完成：

```text
rewritten_query
→ Dense Top-N + BM25 Top-N
→ RRF Fusion
→ Fused Top-N
→ ContextBuilder
→ LangGraph generate_answer
```

并实现 Dense-only / Hybrid 的配置开关和安全降级。

## 上下文

Day 3 的架构已经支持注入 `Retriever` Protocol，审查建议 Day 4 继续返回统一 `SearchHit`，不要让 Agent 节点感知 Dense/BM25 细节。技术文档要求：

- Dense Top 20；
- BM25 Top 20；
- RRF 融合；
- 保留 Dense、BM25、Fused 分数；
- 任一路无结果时系统不失败；
- 增加混合检索配置开关。

D4-01 已确保 ContextBuilder 实际来源映射进入状态，集成时不得破坏该契约。

## 范围

### 必须完成

1. 新增或完善 `rag/retrieval/pipeline.py`，对 Agent 暴露统一 `retrieve(query)`；
2. 支持至少两种模式：
   - Dense-only；
   - Hybrid（Dense + BM25 + RRF）。
3. 配置项至少包括：
   - Hybrid 是否启用；
   - Dense top_n；
   - BM25 top_n；
   - Fusion top_n；
   - RRF k；
   - 使用清晰默认值，默认值与技术文档目标一致或在交付中说明差异。
4. 在配置和 `.env.example` 中增加对应字段；
5. Pipeline 行为：
   - Dense-only 时不调用 BM25/RRF；
   - Hybrid 时分别调用两路 Retriever；
   - 一路返回空列表时用另一条路径继续；
   - 两路都为空时返回空列表；
   - 若某一路抛出已知可降级异常，记录可测试的降级结果并继续另一条路径；
   - 不吞掉编程错误或数据契约冲突。
6. 结果必须是统一 `SearchHit`：
   - Dense-only 保留 dense_score；
   - Hybrid 结果保留 dense_score/bm25_score/fused_score；
   - 不产生 rerank_score。
7. 将 Hybrid Pipeline 通过现有依赖注入接入 LangGraph，不在 `agent/nodes.py` 中写 Dense/BM25 分支逻辑；
8. 保证 Query Rewrite 结果仍是实际检索 query；
9. 保证 ContextBuilder 的实际 sources/used_chunk_ids 契约仍被保留；
10. 增加集成测试：
    - Dense-only 调用路径；
    - Hybrid 两路都命中；
    - Dense 空、BM25 有结果；
    - BM25 空、Dense 有结果；
    - 单路可降级异常；
    - 两路都空；
    - RRF 参数传递；
    - LangGraph RAG 分支使用 rewritten_query；
    - Direct 分支仍不调用任何 Retriever；
    - score 和 source mapping 不丢失。
11. 如 Ingestion 当前已有可用 Chunk 列表/存储，接入 BM25 索引初始化或重建；若必须从 Chroma 读取所有 Chunk，应使用仓库已有稳定 API，不引入第二份不一致语料。对索引生命周期做最小闭环说明。

### 允许修改

- `backend/src/rag/retrieval/pipeline.py`；
- Dense/BM25/Fusion 的必要接口小修；
- `backend/src/config.py`、`.env.example`；
- Ingestion 或应用装配层的最小 BM25 索引接线；
- `backend/src/agent/graph.py` 或依赖装配代码；
- 对应单元/集成测试。

### 不在范围内

- Reranker；
- Langfuse；
- FastAPI/SSE；
- Streamlit；
- 完整 Evaluation 框架；
- 并发性能优化；
- Elasticsearch 或外部 BM25 服务；
- 大规模应用容器重构。

## 约束

1. Agent 节点只依赖统一 Retriever 接口；
2. 不在 Agent 层实现 Dense/BM25/RRF 细节；
3. 不直接相加 Dense 与 BM25 原始分数；
4. 不破坏 D4-01 的精确来源映射；
5. 不吞掉所有 `Exception`；只对明确的检索服务/空结果场景降级；
6. 配置默认值和范围必须可验证；
7. 默认测试不依赖真实 Embedding API 或 Chroma 外部服务，可使用 Fake Retriever；
8. 不提前实现 Day 5 Reranker/Langfuse。

## 验证方式

### 专项测试

根据仓库实际文件名执行，例如：

```bash
uv run pytest -q   backend/tests/test_retrieval_pipeline.py   backend/tests/test_agent_graph.py   backend/tests/test_ingestion.py
```

### 全量回归

```bash
uv run pytest -q
```

### 必须验证的调用序列

Hybrid 模式：

```text
rewrite_query
→ dense.retrieve(rewritten_query)
→ bm25.retrieve(rewritten_query)
→ rrf.fuse(...)
→ context_builder.build(fused_hits)
→ generate_answer
```

Direct 模式：

```text
route_query
→ direct_answer
```

并断言 Dense、BM25、Fusion 均未被调用。

## 最终交付

1. Hybrid Retrieval Pipeline；
2. Dense-only / Hybrid 配置开关；
3. LangGraph 依赖注入接线；
4. BM25 索引生命周期最小闭环；
5. 单元与集成测试；
6. 改动文件清单；
7. 测试命令与结果；
8. 降级语义说明；
9. 配置项说明；
10. 说明 Day 5 Reranker 应插入 Pipeline 的准确位置；
11. 不提交最终对比实验报告或 Day 5 功能。
