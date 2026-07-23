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

`D5-02`

## 任务名称

实现可替换的 Reranker Client 与 Adapter

## 目标

实现符合项目契约的二阶段重排组件，支持 OpenAI-compatible 或 SiliconFlow 风格的 BGE Reranker 服务，并允许通过依赖注入使用 Fake Client 完成离线测试。

本任务只实现独立 Reranker 能力，不接入完整 Retrieval Pipeline 和 Langfuse。

## 上下文

技术规格要求使用 `BAAI/bge-reranker-v2-m3`，将 RRF Top 20 重排为 Top 5。Day4 已统一使用 `SearchHit`，并保留：

- `dense_score`
- `bm25_score`
- `fused_score`
- `rerank_score`

Reranker 必须在保留已有分数和 metadata 的前提下，只补充 `rerank_score` 并重新排序。

## 范围

### 必须完成

1. 定义稳定的 Reranker 抽象契约：
   - 输入：query + `list[SearchHit]`；
   - 输出：新的 `list[SearchHit]`；
   - 输入为空时直接返回空列表；
   - 不修改调用方传入对象和列表。

2. 实现外部 Rerank Client：
   - 从配置读取 base URL、API key、model、timeout；
   - 支持批量提交 query-document pairs；
   - 严格解析 provider 返回的 index/score；
   - 校验索引范围、重复索引、缺失项和非数值 score；
   - 错误信息不得泄露 API key 或完整文档内容。

3. 实现 Rerank Adapter：
   - 将每个 `SearchHit.text` 作为候选文档；
   - 根据返回 index 将 score 映射回原 SearchHit；
   - 使用模型 score 降序排序；
   - score 相同时采用确定性 tie-break；
   - 支持 `top_k` 截断；
   - 保留原 metadata 和 Dense/BM25/Fused 分数；
   - 只写入 `rerank_score`。

4. 支持禁用模式：
   - 当 `RERANKER_ENABLED=false` 时，不调用外部服务；
   - 禁用逻辑应由上层装配或 No-op 实现完成，不把条件散落到业务代码。

5. 补充配置和类型导出。

### 可修改区域

- `backend/src/config.py`
- `backend/src/rag/retrieval/reranker.py`
- 可新增 `backend/src/rag/reranking/`
- 对应测试文件
- `pyproject.toml` 仅在确有必要时修改

### 不在范围

- Retrieval Pipeline 集成；
- 降级策略编排；
- Langfuse；
- AgentState；
- FastAPI/SSE/UI；
- 本地加载大型 Cross-Encoder 模型。

## 约束

1. 不复制 AnyKB 的多用户配置、数据库依赖或复杂基础设施。
2. 只能复用或迁移与本项目相关的最小逻辑，并保留必要声明。
3. 不允许原地修改传入 SearchHit。
4. 不允许用文本相似度启发式冒充真实 Reranker。
5. 不把 provider 原始响应直接向上层泄露。
6. 默认测试必须完全离线。
7. 统一字段名为 `fused_score`，不得引入 `rrf_score`。

## 验证方式

至少覆盖：

1. 空候选；
2. 单候选；
3. 正常多候选重排；
4. Top-K 截断；
5. 输入对象不可变；
6. 保留 Dense/BM25/Fused 分数；
7. 正确写入 `rerank_score`；
8. provider 返回乱序 index；
9. provider 返回越界 index；
10. provider 返回重复 index；
11. provider 返回缺失/非法 score；
12. timeout、HTTP 错误、空响应；
13. 错误信息不包含 API key 和完整候选文本；
14. 禁用模式不调用 Client。

建议执行：

```bash
uv run pytest backend/tests/test_reranker.py -q
uv run pytest -q
```

## 最终交付

1. Reranker 抽象、Client、Adapter；
2. 配置项与 `.env.example` 更新；
3. 完整单元测试；
4. 一份 `docs/day5_task02_reranker_adapter_report.md`；
5. 最终回复列出接口契约、异常类型、测试结果和未覆盖的 provider 差异。
