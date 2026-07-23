# D4-07：完成 Hybrid Retrieval 对比实验与 Day 4 验收报告

## 任务定位

这是 Day 4 的收尾验收任务。目标不是新增大功能，而是用确定性测试和可复现小型实验证明 Hybrid Retrieval 的行为、质量提升和无回归，并产出 Day 4 完成报告。

## 目标

1. 补齐 Day 4 所有关键测试；
2. 构造关键词型查询集，对比 Dense-only 与 Hybrid；
3. 至少记录 3 个 Hybrid 优于 Dense 的案例；
4. 验证分数、降级、来源映射和 LangGraph 集成；
5. 运行全量测试并产出 `docs/day4_acceptance_report.md`；
6. 明确遗留问题和 Day 5 接口边界。

## 上下文

技术文档 Day 4 验收标准：

- 专有名词和函数名问题可被 BM25 命中；
- Dense 和 BM25 结果可以稳定融合；
- 不同检索器返回相同数据结构；
- 混合检索不会因为某一路无结果而失败；
- 至少记录 3 个 Hybrid 优于 Dense 的案例。

Day 3 审查还要求后续验证：

- ContextBuilder 去重/截断后 citation ID 与 sources 精确对应；
- Agent 不感知 Dense/BM25 细节；
- 全量测试不回归。

本任务可建立 Day 4 专用小型评估脚本或测试夹具，但不得提前实现 Day 7 的完整 A/B/C/D Evaluation 框架。

## 范围

### 必须完成

1. 盘点 D4-01 至 D4-06 的测试覆盖，补齐缺失行为；
2. 准备一个小型、可提交仓库的关键词型检索夹具，至少包含：
   - 精确函数名；
   - 配置键或变量名；
   - 模型/库名称；
   - 中英混合术语；
   - 语义相近但关键词不同的干扰 Chunk。
3. 设计至少 5 个查询，其中至少 3 个应能清楚展示 Hybrid 相比 Dense 的提升；
4. 对每个查询记录：
   - query；
   - relevant chunk IDs；
   - Dense Top-K；
   - BM25 Top-K；
   - Hybrid Top-K；
   - 相关 Chunk 的排名变化；
   - 提升原因简述。
5. 最低可使用以下轻量指标：
   - Hit@K；
   - relevant chunk 首次出现排名；
   - Dense vs Hybrid 排名差；
   - 不要求提前实现 Day 7 的完整 Recall@K/MRR 框架，但可复用纯函数且不得扩展范围。
6. 测试必须覆盖：
   - tokenizer 技术词；
   - BM25 索引映射；
   - BM25 SearchHit；
   - RRF 公式和 tie-break；
   - Dense-only/Hybrid 开关；
   - 单路为空；
   - 单路可降级失败；
   - 两路都为空；
   - score 保留；
   - rewritten_query 被使用；
   - Direct 分支零检索；
   - ContextBuilder actual sources 精确映射；
   - Router/Rewrite 结构化输出回归。
7. 执行并记录：
   - Day 4 专项测试数量与结果；
   - 全量测试数量与结果；
   - 如有覆盖率工具，记录相关模块覆盖率；若仓库未配置，不强制新增复杂覆盖率体系。
8. 生成 `docs/day4_acceptance_report.md`，至少包含：
   - Overall Status；
   - Scope；
   - Implementation Summary；
   - Requirement Check 表；
   - Test Results；
   - Dense vs Hybrid Cases；
   - Architecture Check；
   - Known Issues；
   - Impact on Day 5；
   - Final Recommendation。
9. 报告必须区分：
   - 自动化测试证明；
   - Fake/离线实验结果；
   - 真实外部服务 Smoke Test（若执行）；
   - 尚未验证的真实环境能力。

### 允许修改

- Day 4 相关测试；
- 小型检索实验脚本或 fixtures；
- `docs/day4_acceptance_report.md`；
- 为修复验收中发现的 Day 4 缺陷所需的最小代码；
- 不允许借验收名义做无关重构。

### 不在范围内

- BGE Reranker；
- Langfuse；
- FastAPI/SSE/Streamlit；
- Docker；
- 20–30 条 Day 7 Evaluation 数据集；
- LLM-as-a-Judge；
- README 全面包装；
- 新检索策略。

## 约束

1. “Hybrid 优于 Dense”必须有具体查询、相关 Chunk 和排名证据；
2. 不允许只展示 BM25 命中而不展示融合后的最终排名；
3. 不允许只给截图，必须有可复现命令和结构化结果；
4. 测试默认离线、确定性；
5. 如果 3 个提升案例无法构造，应先检查 tokenizer、语料和 RRF，而不是伪造结论；
6. 报告必须诚实记录退化案例或无差异案例；
7. 全量测试失败时不得给出 PASS；
8. 不提前实现 Day 5/Day 7 功能。

## 验证方式

### Day 4 专项测试

使用 pytest marker 或文件列表运行，并在报告中记录收集数量：

```bash
uv run pytest -q <day4-related-test-files>
```

### 全量测试

```bash
uv run pytest -q
```

### 对比实验

提供可复现命令，例如：

```bash
uv run python scripts/compare_dense_hybrid.py
```

或：

```bash
uv run pytest -q backend/tests/test_hybrid_quality_cases.py -s
```

输出至少包含 5 个查询的 Dense/BM25/Hybrid 排名。

### 验收门槛

只有同时满足以下条件才可判定 Day 4 PASS：

- 全量测试通过；
- Day 1–Day 3 无回归；
- 统一 SearchHit 契约成立；
- RRF 数值测试通过；
- 单路为空/失败降级通过；
- 来源映射无错位；
- 至少 3 个关键词型案例中，相关 Chunk 在 Hybrid 中进入 Top-K 或排名明显提升；
- 报告完整、可复现。

## 最终交付

1. 完整 Day 4 测试集；
2. 关键词型对比夹具；
3. 可复现的 Dense/BM25/Hybrid 对比命令；
4. 至少 3 个 Hybrid 优于 Dense 的证据；
5. `docs/day4_acceptance_report.md`；
6. 全量与专项测试结果；
7. 改动文件清单；
8. 已知问题和 Day 5 风险；
9. 明确最终状态：PASS、PASS WITH ISSUES 或 FAIL；
10. 不提交 Reranker、Langfuse、API、UI 或完整 Day 7 Evaluation。
