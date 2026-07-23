# 任务 06：实现基础 RAG Service（Answer + Sources）

> 项目：Adaptive RAG  
> 阶段：Day 2 — 基础问答与结构感知切分  
> 建议执行顺序：6 / 7  
> 前置任务：任务 03、04、05，以及 Day 1 Dense Retrieval  
> 预计单次任务规模：中等偏大，但仍应限制在一次 Codex 会话

## 必须阅读

1. 项目技术文档：`adaptive_rag_project_technical_spec.md`
2. 当前仓库根目录的 `AGENTS.md`（如存在）
3. 与本任务直接相关的现有源码和测试
- AnyKB：无需读取；该 Service 按本项目组件组合，不迁移 AnyKB Agent Tool Loop。

> 不要为了“熟悉项目”无边界浏览整个 AnyKB 仓库。只有任务明确要求时，才阅读指定文件。

## 目标

实现 Day 2 的基础 RAG Service，把 Dense Retrieval、ContextBuilder 和 DeepSeek Client 串成可调用的问答链路，返回答案和结构化来源。

目标链路：

```text
question
→ Dense Retrieval
→ ContextBuilder
→ DeepSeek
→ answer + sources
```

## 上下文

Day 1 已完成向量入库和 Dense Retrieval；任务 04 提供上下文与来源；任务 05 提供 DeepSeek Client。本任务负责业务编排，并建立后续 LangGraph 节点可复用的核心服务。

本阶段不实现 Router、Query Rewrite、Hybrid Retrieval、Rerank、SSE 或前端。

## 范围

### 必须实现

- 新增基础 RAG Service，建议位置：
  - `backend/src/rag/service.py`
  - 或符合现有目录规范的位置
- 定义输入和输出：
  - 输入至少包含 `question`
  - 可选 `knowledge_base_id`、`top_k`
  - 输出至少包含 `answer`、`sources`、`retrieved_chunk_ids`
- 调用 Dense Retriever 获取候选。
- 调用 ContextBuilder 构建上下文和来源。
- 构造明确的系统/用户 Prompt，要求模型：
  - 只依据给定上下文回答文档问题；
  - 无足够依据时明确说明；
  - 使用 `[S1]` 等来源编号；
  - 不伪造来源。
- 调用 DeepSeek Client 生成答案。
- 无检索结果时返回稳定、可解释结果，不能把空上下文伪装成有依据回答。
- 将来源与回答一并返回。
- 通过依赖注入隔离 Retriever、ContextBuilder 和 LLM，便于测试。
- 新增离线单元/集成测试。

### 不在范围内

- 不新增 FastAPI 路由。
- 不实现 SSE。
- 不实现 LangGraph、Router 或 Query Rewrite。
- 不实现 BM25、RRF、Rerank。
- 不实现多轮会话记忆。
- 不接入 Langfuse。
- 不修改 Streamlit。

## 约束

- Service 不得直接访问 Chroma 内部对象；只能通过 Retriever 抽象。
- Prompt 必须把“上下文”和“用户问题”分隔清楚，降低提示注入和格式混淆。
- 来源编号必须与 ContextBuilder 输出一致。
- 无结果时不得调用一个会声称“根据文档”的 Prompt；可选择直接返回固定说明或调用受约束 Prompt，但行为需测试。
- 模型异常应被转换为业务可理解错误，不吞掉根因。
- 测试必须使用 fake Retriever 和 fake LLM，不依赖网络或真实 Chroma。
- 不提前加入过度抽象的 Agent 层。

## 验证方式

### 自动化测试

至少覆盖：

1. Retriever 返回结果时，Service 正确调用 ContextBuilder 和 LLM。
2. Prompt 中包含问题、上下文和引用规则。
3. 输出包含答案、sources、retrieved_chunk_ids。
4. PDF 来源保留页码。
5. Markdown 来源保留章节。
6. 无检索结果时返回明确的“未找到依据”行为。
7. LLM 失败时抛出项目级错误。
8. 所有测试离线执行。
9. 现有 Day 1 ingestion/retrieval 测试不回归。

建议命令：

```bash
uv run pytest backend/tests/test_rag_service.py backend/tests/test_context_builder.py backend/tests/test_retrieval.py -q
```

### 最小真实链路验收

在本地已配置 API Key、Chroma 已入库的前提下，执行至少两个问题：

1. 针对 Markdown 文档的问题：答案包含来源文件和章节。
2. 针对 PDF 文档的问题：答案包含来源文件和页码。

记录输入、返回答案、sources，不要求此 smoke test 进入 CI。

## 最终交付

- 基础 RAG Service 实现
- 必要的请求/响应 Schema
- Prompt 模板或常量
- 离线测试
- 最小真实链路验收记录
- 完成说明：
  - 调用链
  - 无结果行为
  - 错误处理
  - 测试命令与结果
