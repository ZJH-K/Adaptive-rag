# Task 05：LangGraph 组装、集成测试与 Day 3 验收


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

- Task 01～Task 04 均已通过验收；
- 五个节点可独立导入和测试；
- Day 1、Day 2 的现有测试通过。

本任务负责组装和验证，不重新实现节点业务逻辑。

## 目标

按技术文档构建并编译完整 LangGraph：

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

并通过自动化测试证明：

- 通用问题走 Direct Answer；
- 文档问题走 RAG；
- 指代问题先 Rewrite；
- 状态字段完整保留；
- 两条分支没有互相越界调用。

## 上下文

技术文档明确要求：

- Router 能稳定输出结构化结果；
- 通用问题走 Direct Answer；
- 文档问题走 RAG；
- 模糊指代问题能被 Rewrite；
- LangGraph 状态中保留路由原因和改写结果。

必须覆盖的测试问题：

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

## 范围

建议修改或创建：

```text
backend/src/agent/graph.py
backend/tests/test_agent_graph.py
```

如项目测试组织已有约定，可使用等价路径，但不得把所有测试塞入无关文件。

具体实现：

1. 使用 LangGraph 的 `StateGraph` 和 `AgentState` 创建图。
2. 注册以下节点：
   - `route_query`
   - `direct_answer`
   - `rewrite_query`
   - `retrieve`
   - `generate_answer`
3. 添加入口边：
   - `START -> route_query`
4. 根据 `need_retrieval` 添加条件边：
   - `False -> direct_answer`
   - `True -> rewrite_query`
5. 添加顺序边：
   - `rewrite_query -> retrieve`
   - `retrieve -> generate_answer`
6. 添加结束边：
   - `direct_answer -> END`
   - `generate_answer -> END`
7. 提供清晰的 Graph 构建或获取入口，例如：
   - `build_graph(...)`
   - 或项目现有命名规范下的等价函数
8. 依赖应可在测试中替换为 Fake/Mock，不建设复杂容器。
9. 图应编译一次或按项目生命周期合理管理，避免每次节点执行时重复编译。
10. 添加集成测试，验证节点执行顺序和状态结果。

### 必测断言

#### Direct 分支

- `need_retrieval is False`
- `route_reason` 存在
- `answer` 存在
- Rewrite 未被调用
- Retriever 未被调用
- `retrieved_documents` 不应被伪造

#### RAG 分支

- `need_retrieval is True`
- `route_reason` 存在
- `rewritten_query` 存在
- Retriever 使用 `rewritten_query`
- `retrieved_documents` 存在
- `context` 存在
- `answer` 存在
- 节点顺序为 Route → Rewrite → Retrieve → Generate

#### 指代问题

为以下问题提供包含必要实体的历史：

```text
上面提到的状态保存机制有什么限制？
```

断言改写后能独立表达 LangGraph checkpoint 状态保存机制及其“限制”意图。

#### 错误场景

至少覆盖：

- Router 结构化输出无法解析；
- Rewrite 结构化输出无法解析；
- Retriever 返回空列表。

11. 执行完整测试，确认 Day 1、Day 2 无回归。
12. 使用 Fake/Mock 完成确定性 Smoke Test，并在完成报告中记录四个测试问题的路由结果。
13. 检查 `git diff`，确保没有 Day 4+ 功能和无关重构。

## 约束

- 图拓扑必须与技术文档一致；
- 不增加多 Agent、Tool Loop 或自主规划；
- 不引入 Checkpointer、长期记忆或会话持久化；
- 不实现 BM25、RRF、Reranker、Langfuse；
- 不实现 FastAPI、SSE、Streamlit；
- 不把 Direct Answer 和 RAG 合并为一个不可观察的大函数；
- 不让条件边通过重新调用 LLM 决策；应使用 `route_query` 已写入的 `need_retrieval`；
- 不在测试中访问真实 LLM、Embedding 或外部服务；
- 不为了测试通过删除或弱化已有测试；
- 不提交密钥、`.env`、缓存、临时数据库或运行产物。

## 验证方式

从 `backend/` 目录执行任务级测试：

```bash
uv run pytest tests/test_agent_graph.py -q
```

执行全部测试：

```bash
uv run pytest -q
```

可选执行最小导入检查：

```bash
uv run python -c "from src.agent.graph import build_graph; print(build_graph)"
```

最终人工 Review 清单：

- [ ] Graph 拓扑与技术文档一致
- [ ] Direct 分支不检索
- [ ] RAG 分支先 Rewrite 再检索
- [ ] Route 和 Rewrite 结果保留在最终状态
- [ ] 检索结果和 Context 保留在最终状态
- [ ] 四个指定问题均有确定性测试
- [ ] 非法 Router 输出有降级
- [ ] 非法 Rewrite 输出有降级
- [ ] 空检索结果不崩溃、不伪造依据
- [ ] 全量测试通过
- [ ] 无 Day 4+ 功能
- [ ] 无无关重构和敏感信息

## 最终交付

- `backend/src/agent/graph.py`
- `backend/tests/test_agent_graph.py`
- 必要的最小集成调整
- 四个指定问题的测试或 Smoke Test 结果
- 全量测试结果
- Day 3 Definition of Done 核对结果
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
