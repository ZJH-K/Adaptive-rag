# Day 4 Review Report

## Overall Status

**PASS WITH ISSUES**

## Summary

Day4 的核心功能已经完成：中文/技术词 Tokenizer、BM25 内存索引、BM25 Retriever、RRF、Dense-only/Hybrid Pipeline、统一 `SearchHit`、分数保留、LangGraph 接入、来源映射修复、结构化输出契约修复，以及可复现的离线对比材料均已落地。实现没有提前引入 Reranker、Langfuse、FastAPI、SSE、Streamlit、Docker 或 Day7 完整 Evaluation，范围控制正确。

本次独立复测结果为 **309 passed, 1 skipped, 3 warnings**；相关模块专项复测为 **105 passed，96% statement coverage**。离线脚本复现 5 个查询中 4 个排名提升，Dense Hit@3 为 2/5，Hybrid Hit@3 为 5/5。

Day4 主体可以作为后续 Rerank 的基础，但尚不能判定为无条件 PASS。当前有三个需要在后续集成前解决的主要问题：持久化 Chroma 在进程重启后没有生产级 BM25 自动恢复装配；检索诊断使用共享可变 `last_diagnostics`，不具备并发请求隔离；Pipeline 的 Top-N 配置只对既有结果切片，未真正控制底层 Retriever 的召回数量。此外，默认 `deepseek-chat` 模型面临即将到来的服务端弃用风险，可能直接影响 Day5–Day7 的真实 Smoke、Trace 和 Demo。

## Requirement Check

| Requirement | Status | Notes |
|---|---|---|
| D4-01 ContextBuilder 精确来源映射 | PASS | `context_sources` 与 `context_chunk_ids` 已进入 `AgentState`；去重、截断和 citation 连续编号测试覆盖充分。 |
| D4-02 Router/Rewrite 结构化输出契约 | PASS WITH LIMITATION | 已使用 `response_format={"type":"json_object"}`、严格 Pydantic 校验、包装 JSON 提取与确定性降级；真实 DeepSeek Smoke 存在但本次默认跳过，未提供真实执行证据。 |
| D4-03 中文 Tokenizer 与 BM25 索引 | PASS | Tokenizer 可注入，技术词、空文本、重复 ID、重建和位置映射均有测试。 |
| D4-04 BM25 Retriever | PASS | 返回统一 `SearchHit`，保留完整 Chunk metadata 和 `bm25_score`；空查询、空索引、零分、同分和边界已覆盖。 |
| D4-05 RRF Fusion | PASS | 严格按排名计算，rank 从 1 开始；交集、空路、冲突、重复、tie-break、输入不可变和公式精度均有测试。 |
| D4-06 Dense-only/Hybrid Pipeline | PARTIAL | 默认主链路、配置开关、空路、Embedding 失败降级和 LangGraph 注入成立；启动恢复、并发诊断隔离及 Top-N 的端到端配置语义未闭环。 |
| D4-07 对比实验与验收报告 | PASS WITH LIMITATION | 5 个离线查询、4 个提升案例和结构化脚本可复现；Dense 排名是手工固定的 Fake 数据，不证明真实 BGE-M3 上的收益。 |
| 专有名词/函数名可被 BM25 命中 | PASS | `thread_id`、`similarity_search`、`RRF`、`BAAI/bge-reranker-v2-m3` 均有确定性证据。 |
| Dense/BM25 稳定融合并保留三类分数 | PASS | 实际 Chroma + BM25 集成测试证明 metadata 对齐，融合结果保留 `dense_score`、`bm25_score`、`fused_score`。 |
| 任一路为空时 Hybrid 不失败 | PASS | Dense 空、BM25 空、双路空均有测试。 |
| Agent 不感知 Dense/BM25/RRF 细节 | PASS | Agent 仍只依赖统一 `Retriever.retrieve(query)`；检索策略位于 `rag/retrieval/pipeline.py`。 |
| Day1–Day3 无回归 | PASS | 全量 309 项通过，唯一跳过项为显式 opt-in 的外部 LLM Smoke。 |
| 未提前实现 Day5–Day7 功能 | PASS | 未发现 Reranker、Langfuse、API/UI、Docker 或完整 Evaluation 越界实现。 |

## Findings

### Critical

- 无。

### Major

#### M1. 持久化 Chroma 重启后，BM25 索引没有生产装配级自动恢复

证据：

- `backend/src/rag/ingestion/pipeline.py:93-94` 只在一次成功 ingestion 之后，且调用方显式注入 `BM25Index` 时，才从 Chroma 全量重建索引。
- `backend/tests/test_ingestion.py:241-242` 的“重启恢复”由测试代码手动执行 `BM25Index.from_chunks(store.get_all_chunks())`；它证明组件可以恢复，不证明应用启动时会恢复。
- 当前仓库没有应用 composition root、bootstrap 或工厂把持久化 Chroma、恢复后的 BM25Index、BM25Retriever、HybridRetrievalPipeline 和 LangGraph 装配在一起。

结果是：进程 A 完成入库并持久化 Chroma 后，进程 B 新建的 `BM25Index` 默认仍为空；在再次 ingestion 或调用方手工恢复前，所谓 Hybrid 实际会退化为 Dense-only。该退化没有显式状态，也不会被当前端到端测试发现。

影响：Day5 的 Rerank 候选、Day6 的服务重启与“加载内置知识库”、Day7 的 Docker/Evaluation 都可能得到不一致结果。应在应用装配阶段建立唯一、可测试的启动恢复路径，并验证“重启后首次查询即包含 BM25 结果”。

#### M2. `last_diagnostics` 是共享可变状态，无法安全支撑并发 API 与 Langfuse Trace

证据：

- `backend/src/rag/retrieval/pipeline.py:97` 把诊断保存为 Pipeline 实例字段。
- `backend/src/rag/retrieval/pipeline.py:101` 在每次请求开始时清空该字段，并在 `:116-121` 或 `:140-145` 覆盖写入。
- 测试只在单线程中于 `retrieve()` 返回后读取该字段，没有并发请求隔离测试。

如果 Day6 把一个 Pipeline 实例作为 FastAPI 共享依赖，请求 A 返回后、读取诊断前，请求 B 可以覆盖 `last_diagnostics`。Day5 Langfuse 或 Day6 SSE 随后可能把 B 的 mode/count/degraded source 记录到 A 的 Trace 或事件中。

影响：不会直接改变本次检索结果，但会破坏可观测性可信度，且可能造成错误的用户可见过程信息。诊断应作为当前调用的返回值、请求局部状态或上下文数据传播，而不是保存在共享服务实例上。

#### M3. Top-N 配置不是底层召回数量的权威来源

证据：

- `backend/src/rag/retrieval/pipeline.py:109-114` 与 `:128-133` 先调用无参数 `retrieve(query)`，再对返回结果做切片。
- `DenseRetriever` 自己在 `backend/src/rag/retrieval/dense.py:35` 保存固定 `top_k`，并在 `:52-55` 将该值传给 Chroma。
- `BM25Retriever` 同样在 `backend/src/rag/retrieval/bm25.py:20` 保存固定 `top_n`，Pipeline 配置不能提高它。
- `test_candidate_limits_and_rrf_parameters_are_forwarded` 使用一次性返回 4 条结果的 Fake Retriever，只证明切片行为，没有证明配置传到了 Chroma/BM25 查询。

因此，若 `DENSE_TOP_N=50` 而底层 DenseRetriever 仍按默认 20 构造，实际只召回 20；反过来，底层召回 100 后 Pipeline 再切 20，会产生不必要成本。Day5 要求候选过召回时，这种双重配置很容易导致“配置看似生效、实际未生效”。

影响：默认值均为 20 时暂不破坏 Day4 演示，但会影响 Day5 Reranker 候选池、Day7 A/B 实验可信度和调参可解释性。需要在装配层确保一个配置源真正控制底层 Retriever，或让调用接口显式接受候选上限。

#### M4. 默认 DeepSeek 模型配置在 Day5–Day7 时间窗口存在服务可用性风险

证据：

- `.env.example:12` 与 `backend/src/config.py:31` 默认使用 `deepseek-chat`，相关测试也把该模型名硬编码为默认契约。
- 截至本次审核日期 2026-07-22，DeepSeek 官方文档提示 `deepseek-chat` 将于 2026-07-24 弃用；这与 Day5–Day7 的真实 LLM、Langfuse、Demo 验证窗口重叠。参考：[DeepSeek 官方 API 文档](https://api-docs.deepseek.com/)。

配置本身可覆盖，因此这不是架构重写问题；但如果继续沿用示例默认值，外部 Smoke 或最终 Demo 可能在代码未变化的情况下失败。进入 Day5 前应确认账号实际可用模型并保存一次真实 Smoke 证据，同时避免让离线测试把即将失效的服务默认值固化为产品行为。

### Minor

#### m1. BM25 重建与 Chroma 写入不是一个一致性边界

`IngestionPipeline` 先执行 Chroma upsert，再读取全部 Chunk 并重建 BM25。若后半段失败，调用会报错，但 Chroma 已包含新数据、BM25 仍保持旧索引，形成可检索状态分裂。当前测试覆盖 Embedding 失败不写入，却未覆盖“向量写入成功、BM25 重建失败”。在 Day6 上传接口接入前，应定义失败状态、重试或重新构建策略。

#### m2. BM25 索引重建与查询没有并发一致性保证

`BM25Index.rebuild()` 依次替换 `_chunks`、`_chunk_ids`、`_tokenized_corpus` 和 `_model`，没有锁或不可变快照整体替换。上传线程重建时，查询线程理论上可能观察到新 Chunk 映射配旧 BM25 模型。任务包明确不要求 Day4 做并发优化，因此本次不升级为 Major；但 Day6 支持上传后立即提问时必须处理。

#### m3. 对比实验是行为证明，不是检索质量证明

`backend/scripts/compare_dense_hybrid.py:88-107` 直接读取 fixture 中预先指定的 Dense 排名，并合成人工 Dense 分数。它能可靠证明真实 BM25/RRF 实现会怎样融合给定排名，也满足 D4-07 允许的离线验收方式；但语料与排名共同由开发者构造，无法排除选择偏差。README 或面试中只能表述为“小型确定性案例”，不能表述为“真实 BGE-M3 实验表明 Hit@3 从 40% 提升到 100%”。

#### m4. Day4 验收报告的 Day5 字段名有一处不一致

`docs/day4_acceptance_report.md:117` 写的是保留 `rrf_score`，实际统一模型字段为 `fused_score`。若 Day5 按报告而非代码实现 Reranker，可能引入第二套字段命名。应以 `SearchHit.fused_score` 为唯一契约。

#### m5. `jieba` 在当前 Python 3.13 环境产生 3 条 `SyntaxWarning`

全量测试仍通过，警告来自第三方包而非项目代码，不影响 Day4 正确性。但 Day7 Docker 应固定并验证 Python 版本，避免本地 3.13 与目标 3.11 镜像产生不同依赖行为或噪声。

## Architecture Assessment

总体架构判断：**正确，具备继续扩展价值。**

优点：

- Tokenizer、BM25 Index、BM25 Retriever、RRF 和 Retrieval Pipeline 分层清楚，各自可独立测试。
- BM25 与 Dense 共用 `Chunk`/`SearchHit`，没有建立平行数据模型。
- RRF 只使用排名，不混合不可比的原始分数；冲突 metadata 会显式失败，而不是静默拼接。
- Agent/LangGraph 继续只依赖统一 Retriever Protocol，未把 Dense/BM25/RRF 分支写进 Agent 节点。
- ContextBuilder 是 citation 编号与实际来源映射的唯一来源，修复了 Day3 最严重的引用错位风险。
- Router/Rewrite 的 provider 参数集中在 LLM Client，Agent 节点不感知 `response_format`。
- Ingestion 仍负责“解析→切分→向量写入”编排，只增加了可选索引刷新，没有让 Parser、Chunker 或 Embedding 承担检索职责。
- 没有引入 Elasticsearch、多租户、复杂 Agent 或无关框架，符合 MVP 与 AnyKB 复用边界。

主要架构缺口集中在“运行时装配与请求级状态”，不是算法模块本身。当前组件接口适合单进程、顺序执行的测试环境；进入 Day5/Day6 后必须明确启动恢复、共享实例生命周期、并发索引更新和逐请求诊断传播，否则好的模块边界会在 API 装配层被破坏。

## Test Assessment

测试质量评价：**良好，算法与离线集成证据充分；生产生命周期与真实质量证据不足。**

本次独立执行：

```text
uv run pytest -q
309 passed, 1 skipped, 3 warnings in 33.87s

相关模块覆盖率复测
105 passed in 28.92s
313 statements, 96% covered
```

优点：

- BM25、索引、Tokenizer 和 RRF 的边界条件测试密度高，不是仅验证 happy path。
- RRF 有公式数值、输入不可变、重复 ID、metadata 冲突和确定性 tie-break 断言。
- 有真实 Chroma adapter + DenseRetriever + BM25Index/BM25Retriever 的离线集成测试，能证明两路 metadata 可融合。
- LangGraph 测试验证 Rewrite → Dense/BM25 → Fusion → Context → Generate 的顺序，并验证 Direct 分支零检索。
- ContextBuilder 测试覆盖内容去重、预算截断后 `[S2]` 的真实映射，直接关闭 Day3 缺陷。
- LLM 测试覆盖 OpenAI SDK 响应形状、JSON mode 参数、fenced/说明文字 JSON、严格字段校验、空响应和安全错误信息。
- 外部 LLM 测试显式 opt-in，默认测试不会依赖网络或泄漏 API Key。

不足：

- 真实 DeepSeek Smoke 本次未执行，`1 skipped` 正是该测试；因此只能确认协议参数正确，不能确认当前账号/模型真实可用。
- 没有“持久化数据→新进程装配→首次 Hybrid 查询”的生产路径测试。
- 没有共享 Pipeline 的并发诊断隔离测试，也没有 ingestion 重建与 retrieval 并发测试。
- Top-N 测试使用返回固定列表的 Fake Retriever，未验证配置真正控制 Chroma/BM25 的候选数量。
- 对比脚本的 Dense 排名是 fixture 输入，不是 Embedding Client/Chroma 现场计算结果。
- 未覆盖 Chroma 写入成功后 BM25 重建失败的数据一致性场景。

测试数量和覆盖率足以证明 Day4 算法实现质量，但不能代替上述生命周期、并发和真实模型证据。

## Impact on Day 5–Day 7

| Phase | Impact | Assessment |
|---|---|---|
| Day5 Reranker | Medium–High | RRF 输出的统一 `SearchHit` 是正确插入点；Reranker 应位于 Fusion 后、ContextBuilder 前，并保留 `dense_score`、`bm25_score`、`fused_score`。开始前应先统一 Top-N 权威配置，避免候选过召回名义值与真实值不同。 |
| Day5 Langfuse/Failure | High | 节点和算法边界适合 span；但不得读取共享 `last_diagnostics` 作为请求事实。应把降级、候选数、耗时和分数绑定到当前请求。Day3 遗留的 LLM/VectorStore 失败策略仍需在本阶段闭环。 |
| Day6 FastAPI/SSE/Streamlit | High | 必须建立启动时 BM25 恢复与单一应用装配；同时处理上传重建和查询并发。SSE `sources` 可直接使用已修复的 `context_sources`，不能从原始 hits 重算。 |
| Day7 Evaluation | High | 可复用当前结构化 fixture/result 形式，但必须用真实 Dense 输出、20–30 条数据和正式 Hit Rate/Recall@K/MRR；需记录索引版本和配置，避免实验重跑漂移。 |
| Day7 Docker/README/Demo | Medium–High | Docker 重启是验证 BM25 自动恢复的关键场景；README 必须诚实区分离线 Fake 排名案例和真实模型评估，并更新实际可用 LLM 模型配置。 |

## Interview Value Assessment

Day4 的面试展示价值较高，是目前项目最有辨识度的部分：

- 能清晰解释为什么 Dense 对函数名、配置键和模型标识可能召回不足；
- 能展示技术词 Tokenizer 如何保留下划线、连字符和版本号；
- 能用公式解释 RRF 为什么只使用 rank、为什么不直接相加 Dense/BM25 分数；
- 能展示统一 `SearchHit` 在 Dense、BM25、Fusion、未来 Rerank 之间的演进；
- 能展示单路为空、已知失败降级、metadata 冲突显式失败等工程判断；
- 有公式级单测、Chroma 集成测试、LangGraph 集成测试和可复现脚本，证据链比单纯 Demo 更扎实；
- ContextBuilder 的精确 citation 映射是很好的“发现并修复隐藏数据契约问题”案例。

面试中应避免三项过度表述：

1. 不要把固定 Fake Dense 排名的 2/5→5/5 说成真实 BGE-M3 线上指标；
2. 不要宣称 BM25 已完整支持重启恢复和并发更新；
3. 不要宣称 Router/Rewrite 已在真实 DeepSeek 环境稳定验证，除非先保存 Smoke 结果。

若补齐真实小样本评估、启动恢复和请求级 Trace，这一阶段可以很好地展示“算法理解 + 架构边界 + 可测试性 + 诚实评估”的综合 RAG 工程能力。

## Recommendation

**Fix Before Next Day**

Day4 算法与主要接口不需要重写。进入 Day5 前建议至少完成：

1. 确定应用装配与启动恢复方案，保证持久化 Chroma 重启后的首次查询即可使用 BM25；
2. 让检索诊断成为请求局部结果，避免共享 `last_diagnostics`；
3. 统一 Dense/BM25/Fusion Top-N 的权威配置路径，为 Day5 候选过召回做好准备；
4. 确认可用 DeepSeek 模型并运行一次真实 Router/Rewrite Smoke，避免 Day5–Day7 外部集成建立在即将失效的默认配置上。

完成以上修正后，可以进入 Reranker 与 Langfuse；BM25 增量持久化和高并发优化仍可保持为后续非 P0 工作。
