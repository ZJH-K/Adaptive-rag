# 任务 01：实现 MarkdownHeadingChunker

> 项目：Adaptive RAG  
> 阶段：Day 2 — 基础问答与结构感知切分  
> 建议执行顺序：1 / 7  
> 前置任务：Day 1 已完成的 `ParsedDocument`、`ParsedPage`、`Chunk`、RecursiveChunker  
> 预计单次任务规模：中等，适合一次 Codex 会话

## 必须阅读

1. 项目技术文档：`adaptive_rag_project_technical_spec.md`
2. 当前仓库根目录的 `AGENTS.md`（如存在）
3. 与本任务直接相关的现有源码和测试
- AnyKB：本任务无需读取；该 Chunker 需要按本项目技术文档自行实现。

> 不要为了“熟悉项目”无边界浏览整个 AnyKB 仓库。只有任务明确要求时，才阅读指定文件。

## 目标

实现面向 Markdown 技术文档的结构感知切分器 `MarkdownHeadingChunker`。切分结果必须保留 Markdown 标题层级，使后续检索结果能够定位到具体章节，并为结构化 Chunk 与 Recursive Baseline 的对比提供基础。

## 上下文

Day 1 已具备 Markdown 解析、统一 Chunk 数据结构、RecursiveChunker、Embedding、Chroma 和 Dense Retrieval。Day 2 需要新增按 `# / ## / ###` 标题边界切分的优化策略。

目标流程：

```text
ParsedDocument / ParsedPage
→ 识别 Markdown 标题层级
→ 维护 heading_path
→ 在同一标题范围内合并正文段落
→ 超出目标长度时进行安全拆分
→ 输出包含 section、heading_path、chunk_strategy 的 Chunk
```

该任务只负责 Markdown 结构感知切分，不负责 Chunker Factory、入库流程改造、Embedding 或检索。

## 范围

### 必须实现

- 新增 `backend/src/rag/chunking/markdown_heading.py`。
- 提供清晰、可测试的 `MarkdownHeadingChunker` 公共接口，并尽量与现有 RecursiveChunker 调用方式一致。
- 支持识别一级、二级、三级标题。
- 维护每个 Chunk 的：
  - `section`
  - `heading_path`
  - `chunk_strategy="markdown_heading"`
  - `source`
  - `source_type`
  - `document_id`
  - `chunk_index`
  - `content_hash`
- 在同一标题节点内按目标长度合并段落。
- 单个段落超长时，复用或抽取现有安全拆分能力，避免无限长 Chunk。
- 保证 Chunk 顺序与原文顺序一致。
- 对无标题 Markdown 提供稳定降级，不得返回空结果。
- 新增对应单元测试。

### 不在范围内

- 不修改 PDF Chunker。
- 不实现 Chunker Factory。
- 不接入 Ingestion Pipeline。
- 不调用 Embedding、Chroma 或 LLM。
- 不修改 API、前端或 LangGraph。
- 不实现 Markdown AST 的完整标准兼容。

## 约束

- 优先复用 Day 1 已有的数据模型和文本拆分工具，禁止复制出第二套不兼容模型。
- 不允许通过简单按字符硬切而丢失标题元数据。
- `heading_path` 必须反映当前标题层级，例如：
  - `["安装"]`
  - `["安装", "环境配置"]`
  - `["安装", "环境配置", "Python 版本"]`
- 标题行不能被无意义地重复到每个 Chunk 中；是否拼入 Chunk 文本应保持统一并在代码注释或测试中明确。
- 结果必须可确定复现：同一输入与配置产生相同 Chunk 顺序和 ID/哈希。
- 不新增重量级 Markdown 解析依赖，除非仓库已存在且确有必要。
- 遵循现有类型标注、日志和异常风格。
- 不对 Day 1 无关模块做重构。

## 验证方式

### 自动化测试

至少覆盖：

1. 一级标题下的多个段落可以合并。
2. 多级标题产生正确 `heading_path`。
3. 切换到同级或上级标题时路径正确回退。
4. 超长章节可拆成多个 Chunk，且每个 Chunk 保留相同章节元数据。
5. 无标题 Markdown 可稳定切分。
6. 空白段落、连续标题、尾部无换行不会导致异常。
7. `chunk_index` 连续，`content_hash` 非空且稳定。
8. 现有 RecursiveChunker 测试不回归。

建议命令：

```bash
uv run pytest backend/tests/test_chunkers.py -q
```

如测试文件已按模块拆分，可执行对应文件。

### 手工检查

准备一个包含三级标题、短章节和超长章节的 Markdown 样例，打印 Chunk 的：

```text
chunk_index | section | heading_path | text preview
```

确认章节边界和原文顺序正确。

## 最终交付

- `backend/src/rag/chunking/markdown_heading.py`
- 新增或更新的 Chunker 单元测试
- 必要的最小公共工具调整
- 一段任务完成说明，包含：
  - 核心设计
  - 关键边界情况
  - 执行的测试命令及结果
  - 未解决问题（如有）

不得只交付代码而不提供测试结果。
