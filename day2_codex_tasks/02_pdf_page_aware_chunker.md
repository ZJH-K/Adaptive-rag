# 任务 02：实现 PDFPageAwareChunker

> 项目：Adaptive RAG  
> 阶段：Day 2 — 基础问答与结构感知切分  
> 建议执行顺序：2 / 7  
> 前置任务：Day 1 已完成的保留页码 PDF Parser、统一 Chunk 数据结构、RecursiveChunker  
> 预计单次任务规模：中等，适合一次 Codex 会话

## 必须阅读

1. 项目技术文档：`adaptive_rag_project_technical_spec.md`
2. 当前仓库根目录的 `AGENTS.md`（如存在）
3. 与本任务直接相关的现有源码和测试
- AnyKB：本任务无需读取；技术文档明确要求页码感知逻辑按本项目重写。

> 不要为了“熟悉项目”无边界浏览整个 AnyKB 仓库。只有任务明确要求时，才阅读指定文件。

## 目标

实现 `PDFPageAwareChunker`，按 PDF 页级结构切分文本并完整保留页码，使检索结果和最终引用能够定位到 PDF 的具体页面。

## 上下文

Day 1 的 PDF Parser 应输出带 `page_number` 的 `ParsedPage`。Day 2 需要在页级结构基础上进行段落/句子切分，而不是先把整个 PDF 拼接后再固定长度切割。

目标流程：

```text
ParsedDocument.pages
→ 按页处理
→ 页内按段落合并
→ 超长段落按句子或安全字符边界拆分
→ 可选地处理相邻页面的小块
→ 输出保留 page 的 Chunk
```

该任务只实现 PDF 页码感知 Chunker，不负责工厂、入库、向量化或引用渲染。

## 范围

### 必须实现

- 新增 `backend/src/rag/chunking/pdf_page_aware.py`。
- 读取 `ParsedPage.page_number` 并写入 `Chunk.page`。
- 页内优先按段落合并，超过目标长度时安全拆分。
- 不得把来源页码不同的大段内容无标记地合并为一个 Chunk。
- 如果实现跨页小块合并，必须：
  - 行为可配置；
  - 元数据语义明确；
  - 不破坏引用页码准确性。
- 对空页、纯空白页、最后一页、单页 PDF 做稳定处理。
- 设置 `chunk_strategy="pdf_page_aware"`。
- 保持 `chunk_index`、`source`、`source_type`、`content_hash` 等字段正确。
- 新增对应单元测试。

### 不在范围内

- 不修改 PDF Parser 的核心解析逻辑，除非测试暴露出阻断性接口问题。
- 不实现 OCR、表格恢复、图片解析或复杂版面重建。
- 不实现 Chunker Factory。
- 不接入 Chroma、Embedding 或 RAG Service。
- 不修改前端或 API。

## 约束

- 页码必须来自 Parser 输出，禁止根据 Chunk 序号推测页码。
- 默认策略应优先保证引用准确性，而不是追求跨页文本连续性。
- 单个 Chunk 不应同时声称属于多个页面却只保存一个页码。
- 如确需表示页范围，应先确认现有 `Chunk` 模型是否支持；禁止擅自扩大数据模型并影响 Day 1 全链路。
- 对超长句子的硬切仅作为最后降级策略。
- 同一输入和参数必须产生确定性输出。
- 不新增 OCR 或 PDF 重型依赖。
- 不进行无关重构。

## 验证方式

### 自动化测试

至少覆盖：

1. 两页 PDF 解析结果生成的 Chunk 分别保存正确页码。
2. 同页多个短段落按目标长度合并。
3. 同页超长段落被拆分，所有子 Chunk 页码不变。
4. 空白页被跳过但不影响后续页码。
5. 单页 PDF 正常切分。
6. `chunk_index` 连续、哈希稳定。
7. 不出现跨页后错误归属单页的 Chunk。
8. RecursiveChunker 和 Parser 现有测试不回归。

建议命令：

```bash
uv run pytest backend/tests/test_chunkers.py backend/tests/test_parsers.py -q
```

### 手工检查

使用至少 2 页、页面文本长度不同的 PDF 样例，输出：

```text
chunk_index | page | text length | text preview
```

确认 Chunk 页码与原 PDF 页面一致。

## 最终交付

- `backend/src/rag/chunking/pdf_page_aware.py`
- 新增或更新的 PDF Chunker 测试
- 必要的最小辅助函数调整
- 完成说明：
  - 页内切分策略
  - 是否支持跨页合并及其默认行为
  - 测试命令和结果
  - 已知限制

不得将 OCR 或复杂 PDF 版面处理夹带进本任务。
