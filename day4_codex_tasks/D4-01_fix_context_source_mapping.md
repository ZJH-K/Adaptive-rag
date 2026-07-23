# D4-01：修复 ContextBuilder 精确来源映射

## 任务定位

这是进入 Day 4 前的阻塞修复。目标不是实现 Hybrid Retrieval，而是先保证后续 Dense、BM25、RRF 产生的候选在经过 ContextBuilder 去重和截断后，回答引用仍能精确映射到真实使用的 Chunk。

## 目标

1. 将 ContextBuilder 实际使用的来源列表和 Chunk ID 纳入稳定的数据契约；
2. 让 LangGraph `retrieve` 节点保留该映射，不再只保存原始 `retrieved_documents` 和字符串 `context`；
3. 保证 `[S1]`、`[S2]` 等 citation ID 与最终上下文中的来源一一对应；
4. 为 Day 6 的 `sources` SSE 事件和 Day 7 的引用评估提供唯一可信来源。

## 上下文

Day 3 审查发现：

- `ContextBuilder` 会按 `content_hash` 去重、按字符预算截断并重新编号来源；
- 当前 `retrieve` 节点丢弃了 `ContextBuildResult.sources` 和 `used_chunk_ids`；
- 如果 API 层未来从原始 `retrieved_documents` 推导来源，可能出现 `[S2]` 指向错误文档的事实归属问题。

当前 Day 3 图拓扑是正确的，不需要重写 LangGraph。应仅补全状态契约和测试。

## 范围

### 必须完成

1. 阅读并确认现有：
   - `backend/src/agent/state.py`；
   - `backend/src/agent/nodes.py`；
   - `backend/src/rag/context_builder.py`；
   - `backend/src/rag/schemas.py`；
   - 相关 Day 2/Day 3 测试。
2. 选择一个最小且稳定的契约，把以下信息写入 Agent 工作流状态或统一响应模型：
   - ContextBuilder 实际生成的 sources；
   - 实际使用的 `chunk_id` 列表；
   - citation ID 到 source/chunk 的确定性映射。
3. `retrieve` 节点必须使用 ContextBuilder 的真实结果，不得再次从原始 hits 推导来源。
4. 保持原有 `retrieved_documents` 字段兼容，除非仓库已有更合理的迁移方式。
5. 增加测试覆盖：
   - 中间候选因 `content_hash` 重复被移除；
   - 某些候选因字符预算被截断；
   - citation ID 连续编号；
   - `[S2]` 对应截断/去重后的第二个真实来源，而不是原始第二条 hit；
   - 图状态中保存的来源与 `context` 完全一致。
6. 补充必要的类型标注和模型序列化测试，确保后续 API 可直接使用该映射。

### 允许修改

- `backend/src/agent/state.py`；
- `backend/src/agent/nodes.py`；
- `backend/src/rag/context_builder.py`；
- `backend/src/rag/schemas.py` 或更合适的稳定契约模块；
- 对应单元测试和图集成测试。

### 不在范围内

- BM25、RRF、Hybrid Retrieval；
- SSE 或前端 sources 展示；
- Reranker；
- Langfuse；
- 大规模重构 Agent/RAG 分层；
- 外部服务异常统一降级。

## 约束

1. ContextBuilder 是 citation 编号的唯一来源，其他层不得重新编号；
2. 不允许通过“原始 hits 顺序通常一致”来规避精确映射；
3. 不复制第二套 `SearchHit`；
4. 不破坏 Day 1–Day 3 已有接口和测试；
5. 状态新增字段命名必须清楚表达“实际用于上下文”，避免与“所有召回候选”混淆；
6. 不把模型私有思维链写入状态；
7. 只做必要修复，不顺便实现 Day 4 功能。

## 验证方式

### 自动化验证

至少执行：

```bash
uv run pytest -q
```

并单独运行本任务相关测试，例如：

```bash
uv run pytest -q backend/tests/test_context_builder.py backend/tests/test_agent_nodes.py backend/tests/test_agent_graph.py
```

如果仓库实际测试文件名不同，使用对应文件并在交付说明中列出。

### 必须断言的行为

构造候选 `a、b、c`，其中 `b` 与 `a` 内容重复：

- 原始 hits 顺序仍可为 `a、b、c`；
- 最终上下文应只包含 `a、c`；
- `[S1]` 映射到 `a`；
- `[S2]` 映射到 `c`；
- 状态中的实际来源列表、used chunk IDs 与上下文编号完全一致。

再构造超出字符预算的候选，确认未进入上下文的 hit 不出现在实际 sources 中。

## 最终交付

1. 完成上述代码修改；
2. 新增或更新对应测试；
3. 提供改动文件清单；
4. 提供测试命令和真实测试结果；
5. 说明最终采用的数据契约；
6. 说明 Day 6 应直接读取哪个字段生成 sources 事件；
7. 记录任何兼容性风险或未完成项；
8. 不提交 Day 4 Hybrid Retrieval 代码。
