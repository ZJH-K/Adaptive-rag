# Task 02：Router 与 Direct Answer 节点


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

- Task 01 已通过验收；
- `AgentState`、`RouteDecision` 和 Router Prompt 可用；
- Day 2 的 LLM Client 可用或具备可注入的 Fake/Mock。

本任务实现节点，不构建完整 LangGraph。

## 目标

实现自适应工作流的入口判断和无需检索分支：

```text
question + chat_history
          ↓
      route_query
          ↓
need_retrieval + route_reason
          ↓
  direct_answer（仅 direct 分支）
          ↓
        answer
```

## 上下文

技术文档要求：

- 通用问题走 Direct Answer；
- 文档问题走 RAG；
- Router 稳定输出结构化结果；
- LangGraph 状态保留路由原因。

测试问题：

无需检索：

```text
什么是 RAG？
请解释 Python list 和 tuple 的区别。
```

需要检索：

```text
我上传的 LangGraph 文档中如何配置 checkpoint？
上面提到的状态保存机制有什么限制？
```

`route_reason` 只用于系统可观察性，应是简短分类依据，不是模型私有思维链。

## 范围

建议修改或创建：

```text
backend/src/agent/nodes.py
backend/tests/test_agent_router.py
```

具体实现：

1. 实现 `route_query` Node。
2. 从状态读取：
   - `question`
   - `chat_history`（可为空）
3. 调用现有 LLM Client，并使用 Task 01 的结构化输出契约解析结果。
4. 返回最小状态增量：
   - `need_retrieval`
   - `route_reason`
5. 实现 `direct_answer` Node。
6. `direct_answer` 只调用 LLM 生成通用回答，返回：
   - `answer`
7. Direct Answer 不传入检索上下文，不调用 Retriever 或 Context Builder。
8. 节点依赖应可注入或可替换，便于测试，不要求建设复杂依赖注入框架。
9. 增加 Router 测试，覆盖：
   - 通用 RAG 概念问题判定为无需检索；
   - Python list/tuple 问题判定为无需检索；
   - “我上传的文档中”问题判定为需要检索；
   - “上面提到的……”上下文依赖问题判定为需要检索；
   - `route_reason` 非空；
   - Direct Answer 返回回答；
   - Direct Answer 不调用 Retriever。
10. 增加 Router 非法结构化输出测试。

### Router 非法输出的默认处理

技术文档要求覆盖“Router 输出无法解析”错误场景，但没有指定具体降级策略。

本任务采用保守默认：

```text
结构化输出解析失败
        ↓
need_retrieval = true
route_reason = "router_output_parse_failed"
```

原因：对技术文档问答系统而言，误走检索通常比遗漏文档依据更安全。实现中应将该行为写入测试，便于后续 Review；如果仓库已有明确错误策略，则遵循现有策略并在完成报告中说明。

## 约束

- 不实现 Query Rewrite；
- 不实现 `retrieve` 或 `generate_answer`；
- 不构建 LangGraph；
- Direct Answer 不访问 Chroma；
- 不在 Router 中执行检索；
- 不让 Router 直接生成最终回答；
- 不使用关键词硬编码代替 LLM Router 的正式实现；
- 测试可使用 Fake Router LLM 返回确定结果，但生产代码仍应支持真实结构化调用；
- 不记录或暴露长篇思维过程；
- 不增加 Day 4+ 功能；
- 不大规模重构 Day 2 LLM Client。

## 验证方式

从 `backend/` 目录执行：

```bash
uv run pytest tests/test_agent_router.py -q
```

再执行相关回归测试：

```bash
uv run pytest -q
```

验收检查：

- 两个通用问题被判定为 Direct；
- 两个文档/上下文问题被判定为 Retrieve；
- `need_retrieval` 和 `route_reason` 正确写入状态；
- Direct Answer 产生 `answer`；
- Direct 分支不访问知识库；
- 非法 Router 输出有确定性降级；
- 测试不依赖真实 LLM API。

## 最终交付

- `route_query` Node
- `direct_answer` Node
- Router 与 Direct Answer 单元测试
- 非法结构化输出降级测试
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
