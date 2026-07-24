# Day 3 Review Report

## Overall Status

**PASS WITH ISSUES**

> 审核范围说明：用户请求首句写的是“Day2 完成情况”，但提供的参考文件、六项检查内容和验收目标均明确指向 Day3。本报告因此审核 Day3（LangGraph Router 与 Query Rewrite）提交 `ea00b03`，以 `cb1b5b8` 作为 Day2 基线。

## Summary

Day3 的代码范围已基本完成：`AgentState`、Router/Rewrite 结构化契约、五个节点、两分支 LangGraph 和离线自动化测试均已落地；图拓扑与技术规格一致，Direct 分支不会检索，RAG 分支严格按 Rewrite → Retrieve → Generate 执行，也没有提前实现 BM25、RRF、Reranker、Langfuse、API 或 UI。

全量测试结果为 **203 passed in 49.73s**，其中 Day3 专项共 **45 tests**。实现质量总体良好，模块职责清晰，依赖可注入，Day1/Day2 未发生测试回归。

但 Day3 尚不能视为“全部验收闭环”：真实 LLM 的结构化输出稳定性没有得到协议级保证或真实 Smoke Test 证明；同时 `retrieve` 节点丢弃了 ContextBuilder 的精确来源映射，后续 Day6 可能把回答中的 `[S2]` 映射到错误文档。另有外部服务错误未形成工作流级降级。这些问题不否定现有功能，但应在继续扩展前明确修正接口契约。

## Requirement Check

| Requirement | Status | Notes |
|---|---|---|
| `AgentState` 包含规格字段并复用 `SearchHit` | PASS | 字段与技术规格完全一致，未复制第二套检索结果模型。 |
| Router 输出结构化契约 | PARTIAL | Pydantic 严格校验和解析失败降级已完成；真实请求仍是普通文本生成后 `json.loads`，未从调用协议保证 JSON。 |
| 保存 `need_retrieval` 与 `route_reason` | PASS | 节点仅返回最小状态增量，原因非空且不会暴露长思维链。 |
| 通用问题进入 Direct 分支 | PASS | 两个规格问题均有节点与图集成测试。 |
| 文档问题进入 RAG 分支 | PASS | 两个规格问题均有确定性图测试。 |
| 指代问题生成独立 `rewritten_query` | PASS | 测试覆盖 LangGraph/checkpoint 实体补全及“限制”意图保留。 |
| Direct 分支不调用 Retriever | PASS | 图测试验证事件顺序及 Retriever 零调用。 |
| RAG 分支按 Rewrite → Retrieve → Generate 执行 | PASS | 拓扑和运行事件断言均符合规格。 |
| 检索结果、上下文和回答写入状态 | PASS WITH RISK | 三项均写入；但 ContextBuilder 的实际 `sources`/`used_chunk_ids` 未保留。 |
| Router/Rewrite 非法输出降级 | PASS | Router 保守进入检索；Rewrite 回退原问题。 |
| 空检索结果不崩溃、不伪造依据 | PASS | 返回固定无依据回答且不调用生成模型。 |
| 节点单测与 LangGraph 集成测试 | PASS | Day3 专项 45 项。 |
| Day1/Day2 回归 | PASS | 全量 203 项测试通过。 |
| 未提前实现 Day4+ 功能 | PASS | 未发现 BM25、RRF、Reranker、Langfuse、SSE、Checkpointer 等越界实现。 |
| Day3 完成/验收报告 | MISSING | 仓库仅有 `docs/day2_acceptance_report.md`，没有 Day3 完成报告或真实运行证据。 |

## Findings

### Critical

- 无。

### Major

#### M1. “稳定结构化输出”目前只由 Prompt 和事后解析保证，真实模型行为未闭环

证据：

- `backend/src/agent/nodes.py:52-58` 与 `95-101` 调用通用 `generate()` 后直接执行 `json.loads`。
- `backend/src/llm/client.py:84-96` 只发送 `model/messages/temperature`，没有结构化输出或 JSON 模式能力。
- Router/Rewrite 测试全部使用预先返回合法 JSON 的 Fake LLM；没有真实 DeepSeek Smoke Test 或 API 形状测试证明模型持续遵守契约。

现有解析失败降级设计是安全的，但它只保证“不崩溃”，不等于 Router “稳定输出结构化结果”。如果模型返回 Markdown fence、前后解释文字或 provider 特有推理文本，Router 会无条件进入检索，Rewrite 会退回原问题，系统可能长期退化为普通 Dense RAG 而不易被察觉。

影响：Day3 核心验收只能判定为部分完成；Day5 的路由 Trace 和 Day7 的自适应检索评估也会失真。

建议：在继续扩展前固定结构化生成契约，并补充至少一项真实服务 Smoke Test或与真实 SDK 响应形状一致的集成测试；同时记录解析失败率，使降级可观察。

#### M2. 图状态没有保留 ContextBuilder 实际使用的来源，后续引用可能错位

证据：

- `backend/src/agent/nodes.py:122-127` 取得 `ContextBuildResult` 后，仅保存完整 `hits` 和 `context`，丢弃 `sources` 与 `used_chunk_ids`。
- `backend/src/rag/context_builder.py:59-93` 会按 `content_hash` 去重、按字符预算截断，并重新连续编号 `[S1]`、`[S2]`。
- 审核复现实例中，检索结果为 `['a', 'b', 'c']`，其中 `b` 被去重；实际上下文编号却为 `[S1]=a`、`[S2]=c`。如果 Day6 从 `retrieved_documents` 的原始顺序生成 sources，`[S2]` 会错误指向 `b`。

影响：Day6 Sources 事件和前端引用定位存在准确性风险；Day7 “引用完整率”评估也会得到错误数据。这属于用户可见的事实归属问题，而非单纯展示细节。

建议：让工作流状态或统一响应对象保存 ContextBuilder 返回的精确来源列表/实际使用 Chunk ID，并以该映射作为 SSE sources 和评估的唯一依据。

#### M3. 外部服务失败仍会中断整个图，没有工作流级失败契约

证据：

- `route_query` 与 `rewrite_query` 的 LLM 调用发生在解析异常处理之外；超时、网络错误和空响应会直接抛出。
- `retrieve` 未定义 Retriever/ContextBuilder 异常的降级或可观察状态。
- `generate_answer` 只把 `LLMError` 转换为 `RAGGenerationError`，仍会终止图执行。
- 现有 Day3 测试覆盖非法文本输出和空结果，但不覆盖 LLM timeout/request error、Retriever error 或 ContextBuilder error。

技术规格已将 DeepSeek 超时列为错误场景，Day5 又以 failure handling 为重点，因此可以将具体降级策略延后到 Day5；但在此之前不应把当前图描述为具备稳定运行能力。

影响：Day5 Langfuse 需要明确错误状态；Day6 SSE 必须能够发出错误/结束事件，而不是连接无说明中断。

建议：最迟在 Day5 定义各节点的失败语义、是否降级、错误状态字段与 Trace 记录，并补齐图级异常测试。

### Minor

#### m1. Router 使用完整聊天历史，没有与 Rewrite 一致的长度边界

`rewrite_query` 在 `backend/src/agent/nodes.py:93` 只取最近 6 条历史，但 `route_query` 在 `:51` 传入全部历史。Day6 API 接受客户端提交的 `chat_history` 后，这会造成不受控的 token 成本、延迟和上下文上限风险。应在进入两个节点前采用同一套历史裁剪/校验策略。

#### m2. Direct Answer 完全忽略聊天历史

`backend/src/agent/nodes.py:76-82` 只发送当前问题。独立通用问题没有问题，但“Python list 有哪些特点？”之后追问“它与 tuple 有什么区别？”时，Router 可能因指代进入错误分支，或 Direct 分支无法理解指代。复杂记忆不是项目目标，但 Day6 的多轮 `chat_history` 已在 API 契约中，应至少支持有限窗口的普通对话上下文。

#### m3. Agent 层从 `rag.service` 导入协议与异常，边界略显反向耦合

`backend/src/agent/nodes.py:20-26` 和 `graph.py:19` 依赖 RAG 编排服务模块中的 `Retriever`、`ContextConstructor`、`RAGGenerationError`。当前规模下可接受，结构化 Protocol 也使 Day4 Hybrid Retriever 可以直接替换；但随着 Retrieval Pipeline、Reranker 和 API 出现，建议将跨层协议放到稳定契约模块，避免 Agent 编排依赖另一个编排层。

#### m4. 缺少 Day3 完成报告

Day3 Definition of Done 要求完成报告列出改动、验证结果和剩余问题。仓库当前没有对应报告，面试展示也缺少一份可复现的真实路由结果记录。

## Architecture Assessment

整体架构符合设计，且是本次实现最强的部分：

- `state.py` 只定义共享状态和结构化契约；
- `prompts.py` 集中管理 Prompt，没有散落到图或节点；
- `nodes.py` 的五个节点职责分明并返回最小状态增量；
- `graph.py` 只负责拓扑组装，不重复业务逻辑；
- Direct 与 RAG 分支边界清楚，条件边复用已写入的 `need_retrieval`，没有二次调用 LLM 决策；
- `retrieve` 只做检索与上下文构建，`generate_answer` 不再次检索；
- Day2 `BasicRAGService` 仅抽取共用 `build_rag_messages()`，改动小且向后兼容；
- 依赖通过 Protocol/参数注入，未引入复杂容器、Tool Loop、多 Agent 或持久化记忆；
- Day4 可将 Hybrid Retrieval 封装为同一 `retrieve(query)` 接口，现有 `SearchHit` 也已预留 Dense/BM25/Fused/Rerank 分数。

主要架构缺口不是图拓扑，而是“上下文使用结果”和“工作流错误”没有成为一等状态。若不提前明确，Day5/Day6 很容易在 API 层重复推导来源或通过捕获通用异常弥补，形成隐藏耦合。

## Test Assessment

测试质量评价：**良好，但对真实集成稳定性的证明不足。**

执行结果：

```text
uv run pytest -q
203 passed in 49.73s

Day3 专项收集：
45 tests
```

优点：

- 覆盖技术规格中的四个指定问题；
- 节点单测和编译图集成测试分层合理；
- 明确断言 Direct 不检索、RAG 节点顺序、改写 Query 传给 Retriever；
- 覆盖非法 Router 输出、非法 Rewrite 输出、空检索结果；
- 测试不调用真实 LLM、Embedding 或 Chroma，确定性和运行速度合理；
- 验证状态字段、元数据和节点最小返回值，测试不是只检查“函数运行不报错”。

不足：

- Fake LLM 根据 Prompt 文本返回预设 JSON，无法证明真实 provider 的结构化输出稳定性；
- 没有测试 ContextBuilder 去重/截断后 citation ID 与 sources 的精确对应；
- 没有 LLM timeout、请求失败、Retriever 异常等图级错误测试；
- 没有 Router 长历史边界测试；
- 没有验证真实编译图的事件如何映射到 Day6 SSE token/sources/error 协议；
- 没有 Day3 专项覆盖率报告。测试数量充足，但不应以数量代替上述关键行为证明。

## Impact on Day 4–Day 7

| Phase | Impact | Assessment |
|---|---|---|
| Day4 Hybrid Retrieval | Low–Medium | `Retriever` Protocol 和 `SearchHit` 分数字段为 BM25/RRF 留出了良好替换点。应保证 Hybrid Pipeline 仍返回统一 `SearchHit`，不要让 Agent 节点感知 Dense/BM25 细节。 |
| Day5 Rerank/Langfuse/Failure | Medium–High | 节点边界天然适合埋点，但必须补齐解析降级、外部异常和检索失败的可观察状态。来源映射应在 Rerank 后、ContextBuilder 后保持一致。 |
| Day6 FastAPI/SSE/Streamlit | High | 当前 LLM/节点是同步、一次性文本返回，尚不能提供真正 token 级流式输出；同时 sources 精确映射已丢失。两项都需要明确适配，不能只把 `graph.invoke()` 包一层 SSE。 |
| Day7 Evaluation/Docker/README | Medium | 图结构和确定性测试有利于实验；但应新增真实 Router/Rewrite 样本集、路由准确率/降级率，以及基于实际使用来源的引用指标。 |

## Interview Value Assessment

当前实现具有较高的面试展示价值：

- 可以清楚解释为什么 LangGraph 只做轻量 Router 和 RAG 编排，而不是复杂 Agent；
- 两条分支和状态流可直接展示，节点职责容易讲清；
- 保守路由降级、Rewrite 回退和空检索无依据回答体现了工程判断；
- Protocol 注入和 45 项专项测试能展示可测试性；
- 没有复制 AnyKB Agent Tool Loop，也没有引入多租户、多 Agent 等无关复杂度。

当前不宜在面试中直接宣称“Router 结构化输出稳定”或“引用链路端到端准确”，除非先补上真实服务证据和精确来源状态。最有价值的后续演示材料应是：四个问题的真实路由/改写记录、一次解析失败的可观察降级、以及 `[S1]` 到文件/页码/章节的严格映射。

## Recommendation

**Fix Before Next Day**

Day3 的主体实现可保留，不需要重写图或节点。进入 Day4 前建议至少完成两项验收门槛：

1. 明确并验证 Router/Rewrite 的真实结构化输出契约，形成可复现证据；
2. 将 ContextBuilder 的实际来源映射纳入工作流状态或统一响应契约。

外部服务失败处理可以结合 Day5 统一完成，但必须在 Day6 SSE 接入前闭环。完成上述修正后，Day3 可升级为 PASS，并能成为稳定的 Day4–Day7 基础。
