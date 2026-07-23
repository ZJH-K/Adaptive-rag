# Task 01：AgentState、结构化输出契约与 Prompt


## 执行前必读

必须阅读：

- `AGENTS.md`
- `adaptive_rag_project_technical_spec.md`
- 当前仓库中与本任务相关的代码和测试

技术文档是需求和架构的唯一规格来源。`AGENTS.md` 约束实现方式、测试、范围和完成报告。

## AnyKB

本任务不需要阅读或复用 AnyKB Agent Tool Loop。

禁止：

- 引入 AnyKB 的 Agent Framework；
- 引入 Tool Loop、多 Agent、用户系统或会话记忆；
- 为 Day 3 增加与轻量路由无关的抽象。


## 依赖与前置条件

- Day 1、Day 2 基础工程可导入；
- 项目已存在或准备引入 LangGraph 依赖；
- 现有 LLM Client 的调用方式已经明确。

本任务只建立工作流契约和 Prompt，不实现节点调用和图编排。

## 目标

建立 Day 3 后续所有 LangGraph 节点共享的稳定契约：

- 定义 `AgentState`；
- 定义 Router 的结构化输出模型；
- 定义 Query Rewrite 的结构化输出模型；
- 实现 Router Prompt；
- 实现 Query Rewrite Prompt；
- 为结构化契约和 Prompt 编写确定性测试。

## 上下文

技术文档规定的核心状态字段为：

```python
class AgentState(TypedDict, total=False):
    question: str
    chat_history: list[dict]

    need_retrieval: bool
    route_reason: str

    rewritten_query: str
    retrieved_documents: list[SearchHit]
    context: str
    answer: str

    trace_id: str
```

Router 输出必须表达：

```json
{
  "need_retrieval": true,
  "reason": "问题涉及当前知识库中的 LangGraph 专有机制"
}
```

Query Rewrite 输出必须表达：

```json
{
  "rewritten_query": "LangGraph checkpoint 机制如何持久化 Agent 状态"
}
```

Router 的判断依据包括：

- 是否依赖用户上传或内置文档；
- 是否包含“文档中”“该项目”“上面提到”“它”等上下文依赖；
- 是否需要精确引用；
- 是否属于可直接回答的通用常识。

Rewrite 必须：

- 补全指代；
- 保留原意；
- 加入必要实体；
- 不添加文档中不存在的结论；
- 只返回一个独立检索问题。

## 范围

建议修改或创建：

```text
backend/src/agent/state.py
backend/src/agent/prompts.py
backend/tests/test_agent_contracts.py
```

具体实现：

1. 在 `state.py` 中定义 `AgentState`。
2. 复用 `rag.schemas.SearchHit`，不得复制第二套 `SearchHit`。
3. 定义 Router 结构化输出模型，例如 `RouteDecision`：
   - `need_retrieval: bool`
   - `reason: str`
4. 定义 Rewrite 结构化输出模型，例如 `RewriteResult`：
   - `rewritten_query: str`
5. 对字符串字段执行必要的非空和去空白校验。
6. 在 `prompts.py` 中提供 Router Prompt 和 Query Rewrite Prompt。
7. Prompt 应明确要求只输出指定结构，不输出 Markdown 代码块或额外解释。
8. Prompt 应区分“通用知识问题”和“依赖当前知识库的问题”。
9. Rewrite Prompt 应能够接收当前问题和必要的 `chat_history`。
10. 增加测试，验证：
    - 合法结构可解析；
    - 缺失字段或错误类型会被拒绝；
    - Prompt 包含关键判断规则；
    - Rewrite Prompt 包含“独立问题、保留原意、不添加结论”等约束。

## 约束

- 不实现 `route_query`、`rewrite_query` 或其他 Node；
- 不构建 LangGraph；
- 不调用真实 LLM API；
- 不增加 BM25、RRF、Reranker 或 Langfuse；
- 不新增与技术文档重复的通用 Agent Schema；
- 不把 Prompt 散落到节点函数内；
- 不将 `route_reason` 设计为长篇思维链；
- 不修改 Day 1、Day 2 的核心数据模型，除非存在明确兼容性错误；
- 若当前项目已经有等价模型，应最小化调整并复用，不得重复定义。

## 验证方式

从 `backend/` 目录执行：

```bash
uv run pytest tests/test_agent_contracts.py -q
```

同时执行静态导入检查：

```bash
uv run python -c "from src.agent.state import AgentState; from src.agent.prompts import ROUTER_PROMPT, QUERY_REWRITE_PROMPT; print('ok')"
```

验收检查：

- `AgentState` 字段与技术文档一致；
- `SearchHit` 来自现有 RAG Schema；
- Router 和 Rewrite 输出可被结构化校验；
- Prompt 不要求模型输出思维链；
- 无真实外部请求；
- 原有测试无回归。

## 最终交付

- `backend/src/agent/state.py`
- `backend/src/agent/prompts.py`
- `backend/tests/test_agent_contracts.py`
- 必要的最小依赖调整
- 测试运行结果
- Codex 完成报告


## Codex 完成报告要求

完成后必须在回复中提供：

~~~markdown
## Changed Files

- path/to/file

## Implementation Summary

- ...

## Verification

Command:

```bash
...
```

Result:

- ...

## Scope Check

- 未实现 Day 4+ 功能
- 未进行无关重构
- 未提交密钥或临时文件

## Remaining Issues

- 无；或明确列出
~~~
