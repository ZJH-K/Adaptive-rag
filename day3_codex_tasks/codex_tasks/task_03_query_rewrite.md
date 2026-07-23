# Task 03：Query Rewrite 节点


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
- Query Rewrite Prompt 和结构化输出模型可用；
- Day 2 的 LLM Client 可用或具备 Fake/Mock。

本任务只实现改写节点，不执行检索，不构建 LangGraph。

## 目标

把依赖上下文、包含指代或表达模糊的问题改写为一个可独立检索的问题：

```text
question + chat_history
          ↓
     rewrite_query
          ↓
   rewritten_query
```

## 上下文

技术文档要求 Query Rewrite：

- 补全指代；
- 保留用户原意；
- 加入必要实体；
- 不主动加入文档中不存在的结论；
- 只生成一个用于检索的独立问题。

示例：

```text
历史上下文：
用户询问 LangGraph checkpoint 如何保存状态。

当前问题：
上面提到的状态保存机制有什么限制？

期望改写：
LangGraph checkpoint 状态保存机制有哪些限制？
```

改写结果用于 Dense Retrieval，不直接展示为答案。

## 范围

建议修改或创建：

```text
backend/src/agent/nodes.py
backend/tests/test_agent_rewrite.py
```

具体实现：

1. 实现 `rewrite_query` Node。
2. 从状态读取：
   - `question`
   - `chat_history`
3. 使用 Task 01 的 Query Rewrite Prompt 和结构化输出模型。
4. 返回最小状态增量：
   - `rewritten_query`
5. 对无指代、已经独立的问题，允许保持原意并做最小改写。
6. 改写结果必须是一个问题或检索语句，不得生成答案、列表或多查询。
7. 增加测试，覆盖：
   - “上面提到的状态保存机制有什么限制？”结合历史被补全；
   - 改写结果包含必要实体，如 `LangGraph`、`checkpoint`；
   - 原问题意图“限制”被保留；
   - 已经独立的问题不会被改成其他主题；
   - 只返回一个 `rewritten_query`；
   - 空白改写结果被视为无效；
   - LLM 返回非法结构时执行确定性降级。

### Rewrite 非法输出的默认处理

技术文档要求覆盖 Query Rewrite JSON 输出测试，但没有指定解析失败时的行为。

本任务采用最小降级：

```text
结构化输出解析失败或 rewritten_query 为空
        ↓
rewritten_query = 原始 question
```

该降级不阻断检索，也不会引入新事实。必须通过测试固定行为。

## 约束

- 不执行 Retriever；
- 不构建 Context；
- 不生成最终 Answer；
- 不产生多个 Query；
- 不扩展为 Multi-Query Retrieval；
- 不加入文档中不存在的事实或结论；
- 不修改 `question` 原值；
- 不把完整聊天历史无上限拼入 Prompt；仅使用完成指代所需的现有历史输入；
- 不引入长期记忆或 Checkpointer；
- 不调用真实外部 API 进行单元测试；
- 不实现 Day 4+ 功能。

## 验证方式

从 `backend/` 目录执行：

```bash
uv run pytest tests/test_agent_rewrite.py -q
```

再执行相关回归测试：

```bash
uv run pytest -q
```

验收检查：

- 指代问题被补全为独立检索问题；
- 必要实体被保留或补全；
- 用户原意未改变；
- 不生成答案或多个查询；
- `rewritten_query` 写入状态；
- 非法输出回退到原始问题；
- 测试不依赖真实 LLM API。

## 最终交付

- `rewrite_query` Node
- Query Rewrite 单元测试
- 非法输出降级测试
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
