# Adaptive RAG Day 1 Development Plan

## 1. 文档定位

本文档是 Adaptive RAG 项目的 Day 1 开发总览，用于：

- 管理 Day 1 开发范围；
- 明确任务依赖和执行顺序；
- 指导 Codex 单次任务分配；
- 作为开发者 Review 和最终验收依据。

本文档不是具体代码实现 Prompt。具体任务要求位于 `codex_tasks/` 目录。

---

## 2. Day 1 总目标

打通最小 RAG 基础链路：

```text
PDF / Markdown
        ↓
Parser
        ↓
Recursive Chunker
        ↓
Embedding
        ↓
Chroma
        ↓
Dense Retrieval
```

Day 1 完成后，系统必须具备：

- 解析 Markdown 文档；
- 解析数字版 PDF 文档；
- 保存 PDF 页码；
- 生成稳定、可追踪的 Chunk；
- 通过 OpenAI-compatible API 生成 Embedding；
- 将 Chunk 和向量持久化到 Chroma；
- 根据 Query 返回相关 Chunk；
- 通过自动化测试和真实 Smoke Test。

---

## 3. Day 1 范围

### 3.1 必须完成

| 模块 | 内容 |
|---|---|
| 工程初始化 | Python 3.11+、uv、pyproject.toml、目录结构 |
| 配置管理 | Pydantic Settings、`.env.example` |
| 数据模型 | ParsedDocument、ParsedPage、Chunk、SearchHit |
| Parser | Markdown Parser、PDF Parser、Parser Factory |
| Chunker | RecursiveChunker |
| Embedding | OpenAI-compatible Embedding Client |
| Vector Store | Chroma 持久化、Upsert、Query |
| Ingestion | 单文件入库 Pipeline |
| Retrieval | Dense Retriever |
| 测试 | 单元测试、集成测试、Smoke Test |

### 3.2 明确不做

Day 1 不实现：

- MarkdownHeadingChunker；
- PDFPageAwareChunker；
- Context Builder；
- DeepSeek 答案生成；
- LangGraph Router；
- Query Rewrite；
- BM25；
- RRF；
- Reranker；
- Langfuse；
- FastAPI；
- SSE；
- Streamlit；
- Docker。

---

## 4. 上下文文档要求

### 4.1 `adaptive_rag_project_technical_spec.md`

所有任务开始前必须阅读。

它是项目在以下方面的唯一技术规格来源：

- 项目定位；
- 总体架构；
- 技术选型；
- 目录结构；
- 数据模型；
- Day 1 范围；
- 验收标准；
- AnyKB 复用边界。

### 4.2 `AGENTS.md`

所有任务都必须遵守。

它负责约束：

- Codex 角色；
- 编码规范；
- 测试要求；
- 依赖规则；
- 任务边界；
- AnyKB 参考规则；
- 完成报告格式。

### 4.3 AnyKB 仓库

仓库地址：

```text
https://github.com/GU-Cryptography/anykb
```

AnyKB 只作为参考项目，不是本项目基础代码库。

| 任务 | 是否查看 AnyKB | 参考范围 |
|---|---:|---|
| Task 1 工程初始化 | 否 | 无 |
| Task 2 Parser | 是 | `backend/src/kb/parsers/` |
| Task 3 RecursiveChunker | 是 | `backend/src/kb/chunker.py` 或仓库中对应切分实现 |
| Task 4 Embedding Client | 否 | 独立实现轻量 Client |
| Task 5 Chroma Vector Store | 否 | AnyKB 不使用本项目选定的 Chroma 方案 |
| Task 6 Ingestion + Dense Retrieval | 可选 | `ingest.py`、`embedding.py`、`kb_search.py` 的职责划分 |
| Task 7 全链路验收 | 否 | 无 |

查看 AnyKB 时遵循：

```text
理解设计 → 识别可复用思路 → 按本项目结构重新实现
```

不得：

- 大规模复制代码；
- 引入 AnyKB 的 ORM、多租户、用户或权限模块；
- 引入 AnyKB Agent Tool Loop；
- 搬运无关依赖；
- 在未确认 LICENSE 前直接复制源码。

---

## 5. 任务拆分与依赖

### Task 1：项目初始化、配置与数据模型

产出工程骨架、Settings 和核心 Schema。

依赖：无。

### Task 2：Markdown/PDF Parser

实现统一解析层，PDF 保留页码。

依赖：Task 1。

### Task 3：RecursiveChunker

实现 Day 1 Baseline Chunker。

依赖：Task 2。

### Task 4：Embedding Client

实现 OpenAI-compatible 文档和 Query Embedding。

依赖：Task 1。

### Task 5：Chroma Vector Store

实现持久化、Upsert 和向量查询。

依赖：Task 3、Task 4。

### Task 6：Ingestion Pipeline 与 Dense Retrieval

串联 Parser、Chunker、Embedding、Chroma。

依赖：Task 1～5。

### Task 7：Day 1 全链路验收

完成自动化集成测试、真实 Smoke Test 和验收文档。

依赖：Task 1～6。

---

## 6. 推荐执行方式

每次只交付一个任务给 Codex：

```text
阅读 AGENTS.md
      ↓
阅读 adaptive_rag_project_technical_spec.md
      ↓
阅读当前任务文件
      ↓
检查当前仓库状态
      ↓
实现当前任务
      ↓
运行验证命令
      ↓
提交完成报告
      ↓
开发者 Review 和验收
```

当前任务未通过时：

- 不进入下一任务；
- 不提前实现后续功能；
- 只修复当前范围内的问题。

---

## 7. Day 1 Definition of Done

只有全部满足以下条件，Day 1 才算完成：

- [ ] 后端工程结构符合技术文档；
- [ ] Settings 和 `.env.example` 完成；
- [ ] 四个核心数据模型完成；
- [ ] Markdown Parser 完成；
- [ ] PDF Parser 完成并保留页码；
- [ ] RecursiveChunker 完成；
- [ ] Chunk ID 和 content hash 稳定；
- [ ] Embedding Client 完成；
- [ ] Chroma 持久化和幂等 Upsert 完成；
- [ ] Ingestion Pipeline 完成；
- [ ] Dense Retriever 完成；
- [ ] Markdown 和 PDF 均可成功入库；
- [ ] 重复入库不会无限新增 Chunk；
- [ ] 重启 Chroma Client 后数据仍存在；
- [ ] 三个测试问题能够返回相关 Chunk；
- [ ] 自动化测试全部通过；
- [ ] 真实 Smoke Test 通过；
- [ ] 未提前实现 Day 2 及之后功能。
