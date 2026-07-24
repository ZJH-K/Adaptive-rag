# Day 2 Review Report

## Overall Status

**PASS WITH ISSUES**

Day 2 计划中的实现项在 `origin/agent/day2-rag-pipeline`（commit `cb1b5b8`）上基本齐全，模块边界、离线测试和引用数据结构总体达到可继续演进的水平。但当前存在两个会污染后续检索/评估结果的 Major 技术风险，并且 Day 2 提交尚未进入当前 `main`。因此不建议直接开始 Day 3；应先明确索引隔离/替换策略，并修复 Markdown 标题信息未进入可检索文本的问题。

## Summary

- 审核基线：`main` commit `44e6d3d`（Day 1）。
- Day 2 审核对象：`origin/agent/day2-rag-pipeline` commit `cb1b5b8`。
- 改动规模：30 个文件，约 `+2872/-27` 行。
- 当前工作区 `main` 干净，但不包含 Day 2 实现；Day 2 仅存在于远端开发分支。
- 隔离副本执行 `uv run --frozen pytest -q`：**158 passed**。
- 隔离副本执行覆盖率：**94% total coverage**；Day 2 核心模块中 `service.py` 100%、`markdown_heading.py` 100%、`pdf_page_aware.py` 100%、`context_builder.py` 98%、`llm/client.py` 99%。
- 未在审核环境调用真实 Embedding/DeepSeek 服务，避免依赖本地密钥。真实链路结论来自对 `backend/scripts/day2_acceptance.py`、验收报告及实现的交叉检查，未独立复跑外部 API 结果。
- `.understand-anything/knowledge-graph.json` 不存在，因此本次影响分析以 Git diff、源码调用链和测试为依据。

## Requirement Check

| Requirement | Status | Notes |
|---|---|---|
| `MarkdownHeadingChunker` | PASS WITH ISSUE | H1-H3、路径回退、稳定 ID、无标题降级和长文本拆分均已实现；但标题仅存 metadata，不进入 Embedding/BM25 文本。 |
| `PDFPageAwareChunker` | PASS WITH ISSUE | 正确保留页码、禁止跨页混合并覆盖边界测试；当前行为与 Day 1 `RecursiveChunker` 的逐页切分实质相同，没有新的检索质量增益。 |
| Chunker Factory | PASS | 三种策略、兼容矩阵、默认策略及领域异常清晰。 |
| Ingestion 集成 | PASS WITH ISSUE | 能显式选择策略且测试覆盖；不同策略或不同参数产生的旧 Chunk 不会被替换，会在同一 collection 中并存。 |
| Context Builder | PASS WITH ISSUE | 有稳定编号、预算、去重、顺序保持和结构化 sources；显示引用优先使用叶子 `section`，会丢失完整标题路径的定位语义。 |
| DeepSeek Client | PASS | 配置、依赖注入、离线 mock、超时/上游/空响应异常映射及密钥保护完整。 |
| Basic RAG Service | PASS WITH ISSUE | Dense → Context → LLM → Answer + Sources 编排清楚，无结果不调用 LLM；未验证模型输出中的引用编号一定属于实际 sources。 |
| 5 个内置技术文档 | PASS | 3 个 Markdown、2 个多页 PDF，均为小型自编测试资料；每份文档有 2 个问题。 |
| Recursive/Optimized 对比 | PASS WITH EVIDENCE LIMITATION | 验收脚本使用隔离 collection，报告记录 1 个 Markdown rank 2 → rank 1 案例；PDF 两种策略结果相同。 |
| Markdown 来源包含章节 | PASS | `ContextSource` 同时保存 section 与 heading_path。 |
| PDF 来源包含页码 | PASS | page 来自 Parser 元数据，ContextBuilder 和 RAGResponse 均保留。 |
| Day 1 无回归 | PASS | 全量 158 个测试通过。 |
| Day 2 进入默认分支 | NOT COMPLETE | 当前 `main` 仍停留在 Day 1；Day 3 若从 `main` 开始将缺少全部 Day 2 基础。 |

## Findings

### Critical

- 无。

### Major

#### M1. 不同 Chunk 策略/参数会在同一 Chroma collection 中累积，污染正式检索和后续评估

证据：

- Chunk ID 包含 `strategy`、`chunk_index` 和文本（`markdown_heading.py:52-58, 99-119`；`recursive.py:150-168`），因此同一文档切换策略或 chunk 参数时会产生新 ID。
- `IngestionPipeline` 只执行 `upsert_chunks`，没有按 `document_id` 删除或替换旧表示（`ingestion/pipeline.py:63-94`）。
- `ChromaVectorStore` 没有 delete/replace 接口；`DenseRetriever` 查询也没有按 `chunk_strategy` 或实验变体过滤（`vectorstore/chroma.py:145-164`；`retrieval/dense.py:46-64`）。
- 测试明确把“同一 document_id 下 recursive 与 markdown_heading 同时存在”定义为期望行为（`test_ingestion.py:215-239`）。

影响：

- Day 3 的 RAG 链路可能同时召回同一内容的多种 Chunk 表示，挤占 top-k。
- Day 4 建 BM25/RRF 时会把重复表示再次纳入索引和融合，造成虚假重复证据。
- Day 6 用户重新选择 chunk strategy 上传同一文档时会累积旧索引。
- Day 7 A/B/C/D 实验若未像 Day 2 脚本一样严格隔离 collection，指标将失真。

要求：在继续 Day 3 前确定正式语义：生产入库应按 document/strategy 替换旧 Chunk，或 collection/namespace 隔离；实验对比必须强制隔离。不能依赖 ContextBuilder 的末端去重来修正召回阶段污染。

#### M2. Markdown 标题结构没有进入可检索文本，标题专有词对 Dense 和未来 BM25 不可见

证据：

- `MarkdownHeadingChunker` 明确移除标题行，只把正文写入 `Chunk.text`（`markdown_heading.py:23-29, 47-69, 74-97`）。
- Ingestion 仅对 `[chunk.text for chunk in chunks]` 生成向量（`ingestion/pipeline.py:86-89`）。
- Dense Retriever 不使用 `section/heading_path` 参与检索（`retrieval/dense.py:46-64`）。

影响：若 API 名称、配置项或关键概念只出现在标题中，结构感知策略反而会删除最有价值的检索信号。Day 4 BM25 若同样索引 `Chunk.text`，标题关键词也无法命中；Day 7 的 Chunk 优化对比可能因此得出不稳定或错误结论。

要求：在 Day 4 前定义统一的 `retrieval_text` 语义，例如将完整 heading path 作为受控前缀参与 Embedding/BM25，同时避免无意义重复到展示正文。补充“查询词仅存在于标题”用例。

#### M3. Day 2 尚未进入当前 `main`，会阻断正确的 Day 3 开发基线

当前 `main` 为 `44e6d3d feat: complete day 1 RAG retrieval pipeline`，Day 2 位于 `origin/agent/day2-rag-pipeline`。这本身不是代码缺陷，但在状态管理上 Day 2 尚未成为项目默认基线。Day 3 必须基于审阅后的 Day 2 分支，不能从当前 `main` 直接继续。

### Minor

#### m1. PDFPageAware 当前没有区别于 Recursive 的算法价值

两者都逐页调用同一个 `RecursiveChunker.split_text`，验收报告也记录 PDF 对比的页序、Chunk 长度和上下文长度完全一致。功能上满足“页码准确”，但“优化 Chunker”的面试展示价值有限。应在 README/面试中如实定位为页码语义保证，而不是检索质量提升；正式增强应由后续 Evaluation 驱动。

#### m2. Markdown 显示引用只使用叶子 section，重复章节名可能无法定位

`ContextBuilder._create_source` 在 section 存在时优先生成 `section {section}`，只有 section 缺失才使用完整 heading path（`context_builder.py:151-158`）。结构化对象仍保留 heading path，因此数据未丢失，但 Prompt 和展示 citation 可能把 `安装 > 配置` 与 `部署 > 配置` 都显示为 `section 配置`。

#### m3. 测试数量和覆盖率高，但检索质量/引用一致性证据偏弱

- 10 条问题主要被验证为“格式正确”；默认验收脚本只运行 `d2-q01` 和 `d2-q10`，没有自动断言 expected document、expected terms、expected location 或 rank。
- RAG Service 测试使用 FakeRetriever + FakeLLM，没有一个完全离线的 `DenseRetriever → ContextBuilder → BasicRAGService` 组件接线测试。
- 没有测试模型返回 `[S9]`、完全不引用或引用与 sources 不一致的行为。
- `test_builtin_corpus_contains_exactly_five_parseable_documents` 将全局文档数锁死为 5；Day 7 若增加评估文档会产生非功能性失败。

这些不构成 Day 2 功能失败，但测试当前主要证明结构和编排正确，不能证明普遍的检索/答案质量。

#### m4. 验收结果可复现性仍依赖未提交环境

验收报告记录使用 `qwen3.7-text-embedding` 和 `deepseek-v4-flash`，而 `.env.example` 默认是 `BAAI/bge-m3` 与 `deepseek-chat`。报告没有保存脚本的原始 JSON 输出或环境锁定信息。案例满足本阶段最低记录要求，但面试或 Day 7 重跑时可能得到不同排名。

## Architecture Assessment

整体模块边界良好：Chunker 不访问 Embedding/Vector Store/LLM；ContextBuilder 不调用模型；DeepSeek Client 不理解 RAG 数据；BasicRAGService 通过 Protocol 组合 Retriever、ContextBuilder 和 LLM；未提前引入 LangGraph、BM25、Rerank、Langfuse、API 或前端。没有发现 AnyKB Agent、多租户、用户系统或无关依赖迁入，符合 `Understand → Redesign → Implement` 的边界。

主要架构缺口在“索引表示的生命周期”：系统已经允许同文档多策略，但 Vector Store 与 Retriever 没有对应的替换、namespace 或 filter 能力。这不是局部测试问题，而是数据模型与检索语义不闭合。应先解决 M1，否则 Day 4/Day 7 会在污染语料上继续叠加算法。

### Day 3–Day 7 Impact

| Day | Impact | Assessment |
|---|---|---|
| Day 3 LangGraph/Router/Rewrite | Medium | ContextBuilder、LLM Client、BasicRAGService 可复用；必须确保 Day 3 基于 Day 2 分支，并避免混合策略语料进入统一 retrieve node。 |
| Day 4 BM25/Hybrid/RRF | High | M1 会制造重复候选，M2 会让标题关键词无法被 BM25 命中；两项应在 Day 4 前修复。 |
| Day 5 Rerank/Langfuse | Medium | 异常边界和 SearchHit 分数字段可承接；若候选池已污染，Rerank 只会重排污染结果。 |
| Day 6 FastAPI/SSE/Streamlit | Medium | 结构化 sources 可直接展示；后续仍需扩展 streaming、knowledge_base_id/collection 选择及稳定的 citation 展示。 |
| Day 7 Evaluation/Docker/README | High | collection 隔离是 A/B/C/D 指标可信度前提；当前单案例和未锁定模型不足以承担最终效果证明。 |

## Test Assessment

测试工程质量总体为 **Good**：158 个测试全部通过，总覆盖率 94%；Day 2 核心模块覆盖率接近 100%；外部 API 均使用 fake/mock；配置、空输入、超时、空响应、密钥泄漏、标题层级、空页、稳定 ID、预算截断、去重、策略兼容和 Day 1 回归均有覆盖。

不足之处是质量测试与组件接线测试：当前高覆盖率主要来自分支/异常路径单元测试，检索效果只记录了一个成功案例，且没有将 10 条问题集转化为可执行的最低质量门槛。Day 7 正式 Evaluation 可以补足指标，但 M1/M2 必须提前处理，否则评估基线不可信。

## Interview Value Assessment

当前展示价值为 **中上，但尚未达到可直接定稿的面试版本**。

优势：

- 可以清晰讲解 Baseline 与 Markdown 结构切分、稳定元数据、Context Budget、离线 LLM Adapter 和依赖注入。
- 验收报告如实承认 PDF 优化没有质量增益，没有虚构结果，这一点有工程可信度。
- 单元测试密度、异常映射和密钥保护体现了工程化意识。

短板：

- PDFPageAware 与 Recursive 无实质差异，不能作为“优化有效”的核心卖点。
- Markdown 结构只用于 citation metadata，没有进入 retrieval representation，容易被面试官追问“标题如何帮助召回”。
- 仅一个 rank 提升案例、无自动指标，暂时只能说明案例，不足以证明普遍提升。
- 多策略共存导致索引污染的问题若未解决，会削弱对 Evaluation 可信度的解释。

## Recommendation

**Fix Before Next Day**

开始 Day 3 前至少完成以下审查条件：

1. 明确并验证同一文档多策略/多参数的索引隔离或替换语义，防止正式检索混用。
2. 让 Markdown heading path 成为可检索表示的一部分，并增加标题专有词查询测试。
3. 补充最小离线组件接线测试；至少断言 Dense 命中、Context sources 对齐和 RAGResponse 传递正确。
4. 在上述问题修复并复审后，将 Day 2 合入默认开发基线，再启动 Day 3。

其余 Minor 项可排入 Day 3–Day 7，但必须在 Day 7 Evaluation 和 README 定稿前关闭或明确记录为已知限制。
