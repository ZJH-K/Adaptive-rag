# Task 04：Retrieve 与 Generate Answer 节点


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

- Task 01、Task 03 已通过验收；
- Day 2 已有可复用的 Dense Retriever；
- Day 2 已有 `ContextBuilder`；
- Day 2 已有 DeepSeek/OpenAI-compatible LLM Client；
- `SearchHit`、引用元数据和基础回答逻辑可用。

若前置能力缺失，应明确报告阻塞，不得在本任务中重写整个 Day 2 Pipeline。

## 目标

实现 RAG 分支中改写之后的两个节点：

```text
rewritten_query
       ↓
    retrieve
       ↓
retrieved_documents + context
       ↓
generate_answer
       ↓
     answer
```

## 上下文

Day 3 只负责把 Day 2 的基础 RAG 能力接入 LangGraph。

本阶段检索链路仍然是：

```text
Query
  ↓
Dense Retrieval
  ↓
Context Builder
  ↓
DeepSeek Generation
```

BM25、RRF、Reranker 属于 Day 4、Day 5，不得提前加入。

## 范围

建议修改或创建：

```text
backend/src/agent/nodes.py
backend/tests/test_agent_rag_nodes.py
```

具体实现：

### `retrieve` Node

1. 优先读取 `rewritten_query` 作为检索 Query。
2. 如果 `rewritten_query` 缺失或为空，安全回退到 `question`。
3. 调用现有 Dense Retriever。
4. 结果统一为现有 `list[SearchHit]`。
5. 调用现有 `ContextBuilder` 构建上下文。
6. 返回最小状态增量：
   - `retrieved_documents`
   - `context`

### `generate_answer` Node

1. 从状态读取：
   - `question`
   - `context`
   - `retrieved_documents`
2. 调用现有 LLM Client 或 Day 2 生成服务。
3. 生成有文档依据的回答。
4. 保留 Day 2 的来源引用行为；如果引用由后续接口层统一处理，至少保证 `retrieved_documents` 未丢失。
5. 返回最小状态增量：
   - `answer`

### 测试

覆盖：

- Retriever 收到的是 `rewritten_query`；
- 缺少 Rewrite 时回退到原问题；
- `SearchHit` 顺序和元数据被保留；
- Context Builder 收到检索结果；
- `retrieved_documents` 与 `context` 写入状态；
- `generate_answer` 使用原始用户问题和构建后的 Context；
- `generate_answer` 不再次调用 Retriever；
- 空检索结果不会导致崩溃；
- 无相关结果时不得伪造文档依据，应返回明确的“未找到足够相关内容”或沿用现有 Day 2 无结果策略。

## 约束

- 只使用 Dense Retrieval；
- 不实现 BM25、Tokenizer、RRF、Reranker；
- 不在 `retrieve` Node 中调用最终生成；
- 不在 `generate_answer` Node 中再次检索；
- 不复制第二套 Context Builder；
- 不复制第二套 RAG Service；
- 不丢失 `SearchHit.metadata`、页码、章节或来源；
- 不调用真实 Embedding、Chroma 或 LLM API 进行单元测试；
- 不构建 LangGraph；
- 不实现流式输出；
- 不实现 FastAPI、SSE 或 Streamlit；
- 对 Day 2 接口的修改必须最小且向后兼容。

## 验证方式

从 `backend/` 目录执行：

```bash
uv run pytest tests/test_agent_rag_nodes.py -q
```

再执行相关回归测试：

```bash
uv run pytest -q
```

验收检查：

- `retrieve` 使用改写后的 Query；
- 检索结果与上下文正确写入状态；
- 来源元数据完整；
- `generate_answer` 只负责生成；
- 空结果行为明确且可测试；
- 无 Day 4+ 检索功能；
- Day 2 现有测试无回归。

## 最终交付

- `retrieve` Node
- `generate_answer` Node
- RAG 节点单元测试
- 必要的最小 Day 2 适配
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
