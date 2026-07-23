# Day 5 Review Report

## Overall Status

**PASS WITH ISSUES**

**Day5 目标尚未全部完成。** Reranker、候选过召回、请求级 diagnostics、失败模型、BM25 启动恢复和 Fake Trace 已形成质量较高的离线实现；独立复测也通过。但真实 Reranker、真实 Langfuse Dashboard Trace 和真实重排质量收益均没有可复现证据，同时检索失败语义、Langfuse 生命周期及并发入库一致性仍存在会影响 Day6 的主要问题。

## Summary

- 独立复测：`386 passed, 3 skipped in 36.06s`。
- 独立覆盖率复测：`2033 statements, 130 missed, 94%`；Day5 核心模块中 `retrieval/pipeline.py` 96%、`reranker.py` 88%、`agent/nodes.py` 92%、`observability/tracing.py` 93%、`observability/langfuse.py` 77%。
- Reranker Adapter、RRF 后重排、Top-K 截断、分数/metadata 保留、失败回退和 Context/Sources 对齐均有可靠离线测试。
- Day4 的三个主要缺口基本关闭：运行时会从持久化 Chroma 恢复 BM25；diagnostics 改为请求局部返回值；Top-N 已下推到底层 Retriever。
- 当前外部配置检查结果为：Reranker 未配置凭据、Langfuse 未启用且未配置凭据；两个外部 Smoke 均为 `SKIPPED`。基础虚拟环境也未安装可选 `langfuse` 依赖。
- 6 条小样本的 `5 improved / 1 unchanged` 可证明排序管线行为，但分数和排名是人工构造的，不能证明 BGE Reranker 的真实质量收益。
- 未发现 FastAPI、SSE、Streamlit、Docker 或正式 Evaluation 等 Day6/Day7 越界实现。

## Requirement Check

| Requirement | Status | Notes |
|---|---|---|
| RRF 候选可被 Reranker 重新排序 | PASS（离线） | Adapter、Pipeline、Graph 和验收集成测试均覆盖；输入对象不被原地修改。 |
| Reranker 失败时回退且不阻断回答 | PASS WITH LIMITATION | `RerankerError` 子类会回退；未知编程错误会传播，设计合理。但未执行真实 Provider 失败 Smoke。 |
| 重排结果、Context 和 Sources 一致 | PASS | `context_chunk_ids`、`context_sources`、引用编号与实际 Context 对齐，集成测试证据充分。 |
| Trace 覆盖 Router、Rewrite、Retrieval、Rerank、Generation | PARTIAL | Fake Observer 验证了 8 阶段；真实 Langfuse 未验收，且 Provider Adapter 没有请求根 span 和真实业务时段。 |
| Trace 数据请求隔离 | PASS（离线） | 请求局部 `RetrievalResult`、独立 `trace_id` 和两线程 Barrier 测试证明无共享 diagnostics 串线。 |
| 持久化 Chroma 重启后首次查询可使用 BM25 | PASS | `build_retrieval_runtime()` 在构造 Retriever 前全量恢复 BM25，restart-to-answer 集成测试通过。 |
| `retrieve_top_n=20`、`rerank_top_k=5` 真实生效 | PASS | Dense/BM25 limit 已显式下推，Fusion 池与最终 Top-K 契约清晰。 |
| Router/Rewrite/Retrieval/Rerank/Generation 失败契约 | PARTIAL | LLM 与 Reranker 路径较完整；BM25/Vector Store 的真实异常类型未进入降级契约。 |
| Langfuse 未配置/失败不影响核心回答 | PASS WITH RISK | 会降级为 No-op，但启用后缺依赖也会静默 No-op，并仍生成看似有效的 `trace_id`。 |
| 外部服务 Smoke 诚实记录 | PASS | 报告明确写明真实 Reranker、Langfuse 为 NOT RUN，没有伪造 PASS。 |
| 前 5 条质量优于未 Rerank | NOT PROVEN | 只有人工 fixture 和 Fake score；没有真实 BGE 请求或自然问题集证据。 |
| 全量测试无回归 | PASS | 独立复测 `386 passed, 3 skipped`。 |
| 未提前实现 Day6/Day7 | PASS | 范围控制正确。 |
| AnyKB 复用边界 | PASS | Reranker 按本项目契约重写，未引入多租户、数据库或复杂 Agent 依赖；报告声明未复制 AnyKB 源码。 |

## Findings

### Critical

- 无。

### Major

#### M1. 原始 Day5 的真实 Langfuse 与真实重排质量验收没有完成

证据：

- `backend/tests/test_reranker_smoke.py:14-19` 在未显式启用或无凭据时跳过；本次独立执行结果为 skip。
- `backend/tests/test_langfuse_smoke.py:14-23` 同样跳过；当前配置实际构造的是 `NoOpTraceObserver`。
- `docs/day5_acceptance_report.md` 明确承认真实 Reranker 和 Langfuse 均为 `NOT RUN`。
- `backend/scripts/compare_rrf_rerank.py` 的 6 条案例使用人工 Dense/BM25 排名和人工 score，只证明 Adapter 与排序行为。

因此，技术规格中的“Langfuse 能看到完整请求链”和“前 5 条结果质量优于未 Rerank”尚未得到真实证据。当前可以声称“离线协议与降级逻辑完成”，不能声称“真实 BGE + Langfuse 端到端完成”。

影响：Day7 Evaluation、README 指标、Trace 截图和面试陈述都可能把行为测试误表述为效果证明。

#### M2. Langfuse Adapter 目前更像事后事件导出器，不是完整、可信的请求级 Trace 生命周期

证据：

- `backend/pyproject.toml:17-19` 将 Langfuse 放在可选 extra；基础安装未包含该包。
- `backend/src/observability/langfuse.py:51-77` 在缺包、配置或构造异常时静默返回 No-op；独立验证表明，即使设置 `LANGFUSE_ENABLED=true` 和测试凭据，缺少 extra 时仍返回 `NoOpTraceObserver`，没有可观察告警。
- No-op 仍生成 32 位 `trace_id`，Day6 如果直接展示该 ID，用户无法判断它只是本地关联 ID、并不存在于 Langfuse。
- `backend/src/observability/langfuse.py:34-47` 在业务阶段结束后才短暂打开 observation；Langfuse span/generation 自身持续时间只是发送/更新时间，真实业务耗时仅作为 metadata 写入。
- 没有 `chat_request` 根 observation 或 parent 关系；`finish_trace()` 对真实 Adapter 使用继承的空实现，最终请求级状态不会被提交到根 Trace。
- 真实 Smoke 仅 `flush()` 并断言本地生成的 ID 长度，不能自动证明 Dashboard 已收到并显示完整链路。

影响：Langfuse 时间轴、延迟分析、请求完成状态和 Day7 截图的工程可信度不足。进入 Day6 前应明确“本地 request ID”与“已导出的 Langfuse trace ID”，并使启用但不可用的观测状态可诊断。

#### M3. 检索失败契约只识别 `EmbeddingRequestError`，BM25 或 Vector Store 的真实故障会绕过降级并中断 Graph

证据：

- `backend/src/rag/retrieval/pipeline.py:297-310` 的 `_retrieve_path()` 对 Dense 和 BM25 共用同一逻辑，但只捕获 `EmbeddingRequestError`。
- `backend/tests/test_workflow_failure_contract.py:75-86` 的 BM25 失败 Fake 也人为抛出 `EmbeddingRequestError`，因此测试通过但没有覆盖真实 BM25 异常类型。
- 独立探针中，Dense 返回有效结果、BM25 抛出 `RuntimeError` 时，Pipeline 直接抛出 `RuntimeError synthetic BM25 index failure`，没有使用 Dense 单路回退。
- 现有测试还明确让部分 `VectorStoreResponseError` 向外传播，说明 Retrieval 层缺少区分“可降级运行故障”和“应终止的数据/编程错误”的统一异常边界。

影响：Day6 共享服务一旦遇到 BM25 tokenizer/index 故障或 Chroma 响应故障，SSE 可能在没有结构化 failure/done 状态的情况下中断，违背 D5-04 为 Day6 提供稳定错误契约的目标。

#### M4. 并发入库可能把较旧 BM25 快照最后发布，`needs_rebuild` 也没有被查询路径消费

证据：

- `backend/src/rag/ingestion/pipeline.py:96-101` 依次执行 Chroma upsert、读取全量 Chunk、重建 BM25；整个序列没有请求级串行化。
- `BM25Index.rebuild()` 只保证单个已构造快照的原子发布。两个上传交错时，较早读取的旧语料可能因 tokenization 较慢而最后发布，覆盖包含更多 Chunk 的新快照。
- 重建失败只设置 `BM25Index.needs_rebuild`；`BM25Retriever.retrieve()` 和 `HybridRetrievalPipeline` 都不检查该标志，后续查询会继续使用旧 BM25，diagnostics 也不会标识索引陈旧。
- 现有测试覆盖原子快照和“失败后标记”，没有覆盖两个并发 ingestion 的最终语料完整性，也没有覆盖标记后的查询行为。

影响：Day6 的“上传完成后立即提问”及并发上传场景可能出现 Dense 已命中新文档、BM25 长期缺失新文档的静默分裂；Day7 Evaluation 也可能得到不可重复结果。

### Minor

#### m1. `agent/nodes.py` 职责和体量增长过快

该文件目前约 800 行，同时承载节点业务、Trace payload 转换、失败映射、脱敏后的阶段记录、终止 Trace 和聊天历史裁剪。Provider SDK 虽已隔离，但工作流节点仍与观测字段高度耦合。Day6 再加入 SSE 事件映射时，容易形成第二套相似转换逻辑并出现字段漂移。

#### m2. 默认配置会制造“启用但必然降级”的 Reranker 状态

`.env.example:21` 默认 `RERANKER_ENABLED=true`，但 API key 为空。默认启动后每个有候选的请求都会进入 Reranker，再因配置错误回退。核心回答不会失败，但会增加误导性 diagnostics 和演示噪声。Day6 health/status 应明确区分 enabled、configured、available。

#### m3. 当前真实 Smoke 不是可重复的 CI 证据

开发者报告记录过真实 DeepSeek Router/Rewrite 成功，但当前环境已无 LLM 凭据，无法独立重放；Reranker/Langfuse 更未执行。外部 Smoke 保持 opt-in 是正确的，但发布前应保存脱敏后的执行日期、模型、trace ID 或截图及明确的运行命令。

## Architecture Assessment

总体架构方向正确：

- Reranker 位于 `Dense/BM25 → RRF → Rerank → ContextBuilder` 的正确边界；
- `SearchHit` 继续作为唯一公开结果模型，原始分数与 metadata 得到保留；
- `build_retrieval_runtime()` 成为 Chroma、BM25、Retriever、Reranker 与 Ingestion 的单一装配入口；
- Agent 只依赖 Retriever/ContextBuilder/LLM/Observer 抽象，没有感知 Chroma、BM25、RRF 或 Provider HTTP 细节；
- diagnostics 和 Trace 数据随请求传播，不再依赖共享 `last_diagnostics`；
- Reranker 和 Langfuse 都支持 Fake/No-op 注入，没有引入 AnyKB 的无关基础设施。

主要架构风险集中在边界语义而非模块位置：Retrieval 没有完整的 typed failure taxonomy；观测抽象的“trace finished/exported”语义与真实 Provider 行为不一致；入库与 BM25 发布缺少跨步骤的一致性控制。这些问题会在 Day6 的并发 API 和 SSE 生命周期中被放大。

## Test Assessment

测试总体质量较高，不能仅用数量概括：

- Reranker Client 对乱序、越界、重复、缺失、非法 score、HTTP/timeout、脱敏、输入不可变和 Top-K 有细致测试；
- Pipeline 覆盖 Dense-only、Hybrid、单路为空、双路为空、Rerank 成功/禁用/降级、Top-N 下推和未知编程错误传播；
- restart-to-answer 集成测试真实关闭并重开 Chroma，再经过 BM25、Hybrid、Rerank、Context、LangGraph 和 Fake Observer；
- Trace 测试覆盖 Direct/RAG 拓扑、降级、fatal、脱敏和两请求交错隔离；
- Context/Sources 的精确一致性测试有实际价值。

仍需补足的测试：

1. 使用 BM25 自身异常或统一 `RetrievalError`，而不是用 `EmbeddingRequestError` 模拟所有检索分支；
2. Chroma 可用但 BM25 失败、BM25 可用但 Chroma/Embedding 失败、两路均为真实类型故障的图级行为；
3. 两个并发 ingestion 的最终 BM25 语料完整性；
4. `needs_rebuild=true` 后查询、恢复与 diagnostics 行为；
5. 安装真实 Langfuse extra 后的 SDK 契约测试、根 Trace/parent 关系和真实业务时间轴；
6. 外部 Langfuse Dashboard 可见性与真实 Reranker 排序结果；
7. 使用自然问题和真实模型分数的最小质量样本，避免把人工 fixture 当作效果评估。

## Day6-Day7 Impact

### Day6

- FastAPI startup 应唯一调用 `build_retrieval_runtime()`，shutdown 应关闭 Chroma 并 flush/shutdown Langfuse。
- 上传端点进入并发前，必须定义 BM25 rebuild 的串行化、版本检查或失败后自动恢复策略。
- SSE 必须把未知检索异常转换为结构化 `error`/`done`，不能依赖当前并不完整的降级捕获。
- API 状态应区分 `trace_id`、`tracing_enabled`、`trace_exported`，避免返回不存在于 Langfuse 的 ID。
- 部署依赖必须显式安装 `observability` extra，否则设置 Langfuse 凭据也只会静默 No-op。

### Day7

- A/B/C/D Evaluation 必须使用真实 Embedding/Reranker 或明确标注的可复现实验环境；当前 6 条人工样本不能进入正式指标。
- README 和简历材料在真实证据完成前，只能表述为“实现了可插拔 Rerank/Trace Adapter 与离线验证”，不能表述为“真实质量显著提升”或“Langfuse 已完成全链路观测”。
- Docker 镜像需固定目标 Python 版本并安装 Langfuse extra；当前独立测试环境为 Python 3.13.13，仍需在项目目标 Python 3.11 环境复测。
- 最终展示应补充真实 Trace 截图/trace ID、真实 Reranker 前后排序和正式 Evaluation 报告。

## Interview Value Assessment

当前实现具有较强的面试展示基础：

- 可以清晰解释为何先过召回再 Cross-Encoder 重排；
- 可以展示统一 `SearchHit`、分数保留、确定性 tie-break 和失败回退；
- 请求级 diagnostics、不可变 BM25 快照、运行时恢复和精确 citation 体现了工程意识；
- Fake/No-op 抽象及高覆盖失败测试比单纯“调用一个 API”更有说服力。

当前展示短板同样明显：

- 没有真实 BGE Reranker 结果，无法回答“实际提升多少”；
- 没有真实 Langfuse Trace，无法展示 Dashboard 时间轴、错误降级和请求关联；
- 人工小样本如果被包装成质量指标，会降低可信度；
- 面试追问并发上传、BM25 陈旧状态或 Trace 导出失败时，当前实现仍有明确缺口。

完成 M1-M4 后，Day5 才能从“设计和离线测试优秀”提升为“真实端到端可演示”。

## Recommendation

**Fix Before Next Day**

建议在正式进入 Day6 主体开发前完成以下门槛：

1. 建立真实 Langfuse Trace 证据，并校正根 Trace、导出状态和实际业务耗时语义；
2. 执行真实 Reranker Smoke，至少证明实际 Provider 契约和一组自然样本排序；
3. 补齐 BM25/Chroma 的 typed failure 与单路降级测试；
4. 解决并发 ingestion 的 BM25 版本倒退及 `needs_rebuild` 恢复路径。

在这些问题关闭前，Day5 不应标记为全部完成，也不建议把当前结果用于 Day7 的最终指标或面试效果声明。
