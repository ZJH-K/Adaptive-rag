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

`D5-06`

## 任务名称

Day5 集成验收、真实 Smoke 与审查材料

## 目标

完成 Day5 的最终集成验证，证明：

- Reranker 能重新排列候选；
- Reranker 失败时系统仍可回答；
- Langfuse 能看到完整请求链；
- Trace 中包含 Rewrite、检索结果、分数和耗时；
- 前 5 条结果在明确的小样本案例中优于未 Rerank 结果；
- Day4 的启动恢复、请求隔离和 Top-N 缺口已关闭。

本任务以测试、证据和报告为主，只允许修复验收中发现的小范围问题。

## 上下文

Day5 的最终价值不只是“有 Reranker 类”和“调用了 Langfuse”，而是要形成可复现证据链。Day4 Review 还指出：

- 真实 DeepSeek Smoke 默认跳过；
- 当前默认模型可能存在服务可用性风险；
- Day4 对比实验使用 Fake Dense 排名，不能被表述为真实质量指标。

因此本任务必须严格区分：

1. 离线确定性行为测试；
2. 真实外部服务 Smoke；
3. 小样本质量观察；
4. 尚未完成的 Day7 正式 Evaluation。

## 范围

### 必须完成

1. 运行全量离线测试并记录结果。
2. 运行 Day5 专项测试并生成覆盖率结果。
3. 增加一条完整本地集成测试：
   - 持久化 Chroma；
   - 新建运行时；
   - BM25 自动恢复；
   - Hybrid；
   - Rerank；
   - ContextBuilder；
   - LangGraph；
   - Fake Langfuse；
   - 最终答案和精确 sources。

4. 准备 5–10 条小型 Rerank 验证集：
   - 包含专有名词、函数名、语义相近干扰项；
   - 对比 RRF 排名与 Rerank 排名；
   - 至少记录命中位置变化；
   - 明确标注为“小样本工程验收”，不是 Day7 正式 Evaluation。

5. 真实外部 Smoke：
   - 检查当前账号实际可用的 DeepSeek 模型，不盲目依赖过时默认值；
   - Router/Rewrite 至少执行一条真实 JSON mode 请求；
   - Reranker 至少执行一条真实请求；
   - Langfuse 至少生成一个真实 Trace；
   - 测试必须 opt-in，凭据只从环境变量读取；
   - 若因无凭据或服务不可用未执行，必须在报告中明确写出，不能伪造 PASS。

6. 更新配置示例：
   - 不把可能失效的具体服务模型硬编码成不可覆盖契约；
   - 测试不要把外部模型名称固定为产品正确性条件；
   - 保留清晰的配置说明。

7. 生成 Day5 总验收报告。

### 可修改区域

- 测试与 fixture；
- scripts；
- docs；
- 配置示例；
- 验收发现的小范围代码问题。

### 不在范围

- FastAPI；
- SSE；
- Streamlit；
- Docker；
- 20–30 条正式 Evaluation；
- README 最终包装；
- Langfuse 自部署。

## 约束

1. 不伪造真实 API 执行结果。
2. 不在仓库提交 API key、完整外部响应或敏感 Trace 数据。
3. Fake 测试结果与真实 Smoke 结果必须分开描述。
4. 小样本 Rerank 观察不能宣称为统计显著提升。
5. 不为了覆盖率重构无关代码。
6. 不提前实现 Day6/Day7。
7. 所有报告字段名以代码中的 `fused_score` 为准。

## 验证方式

必须记录以下命令的实际结果，命令可按仓库结构调整：

```bash
uv run pytest -q
uv run pytest backend/tests/test_reranker.py backend/tests/test_retrieval_pipeline.py backend/tests/test_observability.py backend/tests/test_agent_graph.py -q
uv run pytest --cov=src --cov-report=term-missing
```

可选真实 Smoke：

```bash
RUN_EXTERNAL_LLM_TESTS=1 RUN_EXTERNAL_RERANKER_TESTS=1 RUN_LANGFUSE_SMOKE=1 uv run pytest backend/tests/smoke -q
```

验收清单：

- [ ] 全量测试通过；
- [ ] Day1-Day4 无回归；
- [ ] Rerank 正常路径通过；
- [ ] Rerank 降级路径通过；
- [ ] 请求级 diagnostics 无串线；
- [ ] BM25 重启恢复通过；
- [ ] Top-N 真实生效；
- [ ] Direct/RAG Trace 拓扑正确；
- [ ] sources 与 context citation 严格一致；
- [ ] 真实 Smoke 结果被诚实记录；
- [ ] 未实现 Day6/Day7 越界功能。

## 最终交付

1. `docs/day5_acceptance_report.md`，至少包含：
   - Overall Status；
   - Summary；
   - Requirement Check；
   - Changed Files；
   - Architecture Notes；
   - Test Results；
   - Coverage；
   - Rerank 小样本结果；
   - Langfuse Trace 证据；
   - External Smoke Results；
   - Known Issues；
   - Day6 Readiness；
2. 可复现的小样本脚本与 fixture；
3. 必要的测试修复；
4. 最终回复采用以下结构：
   - Changed Files
   - Implementation Summary
   - Validation Results
   - External Smoke Results
   - Remaining Issues
   - Day6 Readiness
