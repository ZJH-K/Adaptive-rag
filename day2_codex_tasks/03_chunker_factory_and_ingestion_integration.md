# 任务 03：实现 Chunker Factory 并接入 Ingestion Pipeline

> 项目：Adaptive RAG  
> 阶段：Day 2 — 基础问答与结构感知切分  
> 建议执行顺序：3 / 7  
> 前置任务：任务 01、任务 02，以及 Day 1 的 RecursiveChunker 和 Ingestion Pipeline  
> 预计单次任务规模：中等，适合一次 Codex 会话

## 必须阅读

1. 项目技术文档：`adaptive_rag_project_technical_spec.md`
2. 当前仓库根目录的 `AGENTS.md`（如存在）
3. 与本任务直接相关的现有源码和测试
- AnyKB：无需读取；本任务是本项目内部策略编排。

> 不要为了“熟悉项目”无边界浏览整个 AnyKB 仓库。只有任务明确要求时，才阅读指定文件。

## 目标

实现统一的 Chunker Factory，并让 Ingestion Pipeline 能根据显式策略选择 `recursive`、`markdown_heading` 或 `pdf_page_aware`，同时验证策略与文件类型的兼容性。

## 上下文

Day 1 入库流程默认使用 RecursiveChunker。任务 01、02 新增了两种结构感知策略。现在需要在不破坏现有入库、去重和 Chroma 持久化行为的前提下，将策略选择接入正式链路。

预期调用关系：

```text
ingest(document, chunk_strategy)
→ ChunkerFactory.create(strategy, source_type)
→ chunker.chunk(parsed_document)
→ Embedding
→ Chroma upsert
```

## 范围

### 必须实现

- 新增或完善 `backend/src/rag/chunking/factory.py`。
- 支持以下稳定策略名：
  - `recursive`
  - `markdown_heading`
  - `pdf_page_aware`
- 为未知策略返回清晰的领域异常或参数错误。
- 对明显不兼容的组合给出明确行为，例如：
  - PDF + `markdown_heading`
  - Markdown + `pdf_page_aware`
- 修改 Ingestion Pipeline，使其接受并使用 `chunk_strategy`。
- 保持未传策略时的兼容默认值，默认值应与现有系统一致或在配置中明确。
- 确保 Chunk 的 `chunk_strategy` 与实际实现一致。
- 保持 Day 1 的去重、持久化、错误处理和返回统计不回归。
- 增加工厂和入库集成测试。

### 不在范围内

- 不修改 Embedding Client 的协议。
- 不重写 Chroma Adapter。
- 不新增 API 路由。
- 不实现 DeepSeek、ContextBuilder 或 RAG Service。
- 不做多知识库管理。
- 不新增第四种 Chunk 策略。

## 约束

- 禁止在 Ingestion Pipeline 中堆叠大段 `if/elif` 复制 Chunker 初始化逻辑；策略创建应集中在 Factory。
- 策略名应使用受控常量、Literal 或 Enum，避免魔法字符串分散。
- 不兼容策略必须快速失败，错误信息需要包含策略名和文档类型。
- 默认策略变更必须谨慎；若 Day 1 已有外部调用，应保持向后兼容。
- 不允许破坏重复入库去重机制。
- 测试不得依赖真实 Embedding API，使用 fake/mock。
- 不对无关模块做格式化式大改。

## 验证方式

### 自动化测试

至少覆盖：

1. 三个合法策略都能创建正确 Chunker。
2. 未知策略返回明确错误。
3. 不兼容的文档类型和策略被拒绝或按文档约定降级。
4. Markdown 通过 `markdown_heading` 入库后，Chunk 保存章节元数据。
5. PDF 通过 `pdf_page_aware` 入库后，Chunk 保存页码。
6. 默认 `recursive` 路径保持可用。
7. 相同文件、相同策略重复入库不会无限增加 Chunk。
8. 相同文件使用不同策略时的处理行为明确且有测试。
9. 测试中不访问真实网络。

建议命令：

```bash
uv run pytest backend/tests/test_chunkers.py backend/tests/test_ingestion.py -q
```

### 手工检查

分别对一个 Markdown 和一个 PDF 执行三种策略中的合法组合，检查入库结果中的：

```text
document_id
chunks_count
chunk_strategy
page / section / heading_path
```

## 最终交付

- `backend/src/rag/chunking/factory.py`
- 修改后的 `backend/src/rag/ingestion/pipeline.py`
- 必要的策略类型/异常定义
- Factory 和 Ingestion 集成测试
- 完成说明：
  - 支持的策略矩阵
  - 默认策略
  - 不兼容组合行为
  - 测试命令与结果
