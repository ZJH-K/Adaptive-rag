# Adaptive RAG Day 3 Development Plan

## 1. 文档定位

本文档是 Adaptive RAG 项目的 Day 3 开发总览，用于：

- 管理 Day 3 开发范围；
- 明确 Codex 单次任务的执行顺序和依赖；
- 作为开发者 Review、测试和最终验收依据；
- 防止 LangGraph 工作流开发扩展为复杂 Agent 系统。

具体执行要求位于 `codex_tasks/` 目录。每次只向 Codex 分配一个任务文件。

---

## 2. Day 3 总目标

在 Day 1、Day 2 已完成的基础 RAG 能力之上，构建轻量自适应 RAG 工作流：

```text
START
  ↓
route_query
  ├── direct   → direct_answer → END
  └── retrieve → rewrite_query
                       ↓
                    retrieve
                       ↓
                generate_answer
                       ↓
                      END
```

Day 3 完成后，系统必须具备：

- 使用 LangGraph 编排两条明确分支；
- Router 稳定返回结构化路由结果；
- 通用问题不访问知识库，直接调用 LLM 回答；
- 文档相关问题进入 RAG 链路；
- 上下文依赖或指代问题先改写为独立检索问题；
- LangGraph 状态保留路由原因、改写结果、检索结果、上下文和最终回答；
- 使用自动化测试证明各节点和分支行为正确。

---

## 3. 前置条件

开始 Day 3 前，应确认 Day 1、Day 2 的以下能力已经存在并可复用：

- `SearchHit` 等核心数据模型；
- Dense Retrieval；
- `ContextBuilder`；
- DeepSeek/OpenAI-compatible LLM Client；
- 基础 RAG 回答生成能力；
- 引用来源生成或可从 `SearchHit.metadata` 推导来源；
- 现有测试可以通过。

如果当前仓库的接口名称与技术文档不同，Codex 应基于实际代码做最小适配，不得为统一命名而大规模重构 Day 1、Day 2 代码。

---

## 4. 必读资料

每个任务开始前必须阅读：

1. `AGENTS.md`
2. `adaptive_rag_project_technical_spec.md`
3. 当前任务文件
4. 当前仓库中与任务相关的现有实现和测试

技术文档重点章节：

- 项目定位与非目标；
- 项目目录；
- `AgentState`；
- LangGraph 设计；
- Router 输出；
- Query Rewrite 输出；
- Day 3 计划与验收标准；
- 测试要求和错误场景。

### AnyKB 阅读要求

Day 3 不需要阅读或复用 AnyKB Agent Tool Loop。

原因：

- 技术文档明确将 Agent 能力限制为轻量 Router 和 RAG 编排；
- AnyKB Agent Tool Loop 不在复用范围内；
- 引入其 Agent 架构会扩大范围并增加不必要耦合。

---

## 5. Day 3 范围

### 5.1 必须完成

| 模块 | 内容 |
|---|---|
| Agent 契约 | `AgentState`、Router 结构化输出、Rewrite 结构化输出 |
| Prompt | Router Prompt、Query Rewrite Prompt |
| 节点 | `route_query`、`direct_answer`、`rewrite_query`、`retrieve`、`generate_answer` |
| LangGraph | 节点注册、条件边、编译和可调用入口 |
| 测试 | 节点单测、分支集成测试、异常输出测试、手工 Smoke Test |

### 5.2 明确不做

Day 3 不实现：

- BM25；
- 中文 Tokenizer；
- RRF；
- Reranker；
- Langfuse；
- FastAPI 路由；
- SSE；
- Streamlit；
- Docker；
- 多 Agent；
- Tool Loop；
- 长期记忆；
- Checkpointer 持久化；
- 用户或多租户系统；
- Web Search。

---

## 6. 任务拆分与依赖

### Task 01：AgentState、结构化输出契约与 Prompt

建立工作流共享状态、Router/Rewrite 输出模型以及 Prompt。

依赖：Day 1、Day 2 基础工程。

### Task 02：Router 与 Direct Answer 节点

实现路由判断和无需检索时的直接回答。

依赖：Task 01。

### Task 03：Query Rewrite 节点

实现指代补全和独立检索问题生成。

依赖：Task 01。

Task 02 与 Task 03 在 Task 01 完成后可以独立开发，但建议按编号顺序执行，便于 Review。

### Task 04：Retrieve 与 Generate Answer 节点

复用 Day 2 Dense Retrieval、Context Builder 和 LLM Client，完成 RAG 分支节点。

依赖：Task 01、Task 03，以及 Day 2 基础 RAG 能力。

### Task 05：LangGraph 组装、集成测试与 Day 3 验收

按技术文档拓扑构建并编译 LangGraph，验证两条分支和状态传递。

依赖：Task 01～Task 04。

---

## 7. 推荐执行流程

```text
阅读 AGENTS.md
      ↓
阅读技术文档和当前任务
      ↓
检查当前仓库与前置能力
      ↓
列出计划修改文件
      ↓
只实现当前任务
      ↓
运行任务级测试
      ↓
检查 git diff
      ↓
提交 Codex 完成报告
      ↓
开发者 Review 和验收
```

当前任务未通过时：

- 不进入下一任务；
- 不提前实现后续 Day 功能；
- 不通过扩大重构范围来规避问题；
- 明确报告阻塞项和剩余问题。

---

## 8. Day 3 关键设计约束

1. LangGraph 只承担路由和 RAG Pipeline 编排，不建设通用 Agent Framework。
2. Router 与 Rewrite 必须使用可验证的结构化输出契约。
3. `route_reason` 是简短、可观察的路由依据，不是模型私有思维链。
4. Direct 分支不得调用 Retriever、Context Builder 或知识库。
5. RAG 分支必须执行 Rewrite 后再检索。
6. `retrieve` 节点只负责检索和上下文构建，不负责最终生成。
7. `generate_answer` 节点不得再次检索。
8. Day 3 只使用现有 Dense Retrieval，不得提前实现 Hybrid Retrieval。
9. 测试默认使用 Fake/Mock LLM 和 Retriever，不依赖真实外部 API。
10. 节点应返回最小状态增量，避免无意覆盖其他状态字段。

---

## 9. Day 3 Definition of Done

只有全部满足以下条件，Day 3 才算完成：

- [ ] `AgentState` 包含技术文档要求的字段；
- [ ] Router 输出可稳定解析为结构化结果；
- [ ] Router 保存 `need_retrieval` 和 `route_reason`；
- [ ] 通用问题进入 Direct Answer 分支；
- [ ] 文档相关问题进入 RAG 分支；
- [ ] 指代问题能够生成独立 `rewritten_query`；
- [ ] Direct 分支不调用 Retriever；
- [ ] RAG 分支按 Rewrite → Retrieve → Generate 执行；
- [ ] `retrieved_documents`、`context` 和 `answer` 正确写入状态；
- [ ] LangGraph 拓扑与技术文档一致；
- [ ] 节点单元测试通过；
- [ ] LangGraph 集成测试通过；
- [ ] Router 非法结构化输出场景被覆盖；
- [ ] Query Rewrite 非法输出场景被覆盖；
- [ ] 技术文档中的四个测试问题被覆盖；
- [ ] 现有 Day 1、Day 2 测试没有回归；
- [ ] 未实现 Day 4 及之后功能；
- [ ] Codex 完成报告清晰列出改动、验证结果和剩余问题。
