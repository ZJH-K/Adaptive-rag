# Day 1 Task 03：实现 Baseline RecursiveChunker

## 开始前必须阅读

### 项目设计文档

必须阅读：

```text
adaptive_rag_project_technical_spec.md
```

重点查看：

- 第 7 节 AnyKB 复用边界；
- 第 9 节 `Chunk` 数据结构；
- 第 10.1 节 Baseline RecursiveChunker；
- 第 19 节 Day 1 Chunker 任务；
- 第 21 节 Chunker 测试要求。

### 开发规则

必须阅读并遵守：

```text
AGENTS.md
```

### AnyKB 仓库

需要查看：

```text
https://github.com/GU-Cryptography/anykb
```

重点查看：

```text
backend/src/kb/chunker.py
```

如仓库结构发生变化，则定位对应的递归切分实现。

目的：

- 理解其段落、句子和硬切分流程；
- 参考 overlap 的实现思路；
- 识别哪些逻辑可适配到本项目。

注意：

- 不复制 AnyKB 的数据库、知识库或 ORM 依赖；
- 不引入 AnyKB 不相关的数据结构；
- 最终实现必须使用本项目 `Chunk` Schema。

---

## 目标

实现 Day 1 使用的基线递归切分器，把 `ParsedDocument` 转换成稳定、可追踪、可重复生成的 `Chunk` 列表。

---

## 上下文

技术文档定义的 Baseline 流程：

```text
按空行切段落
→ 超长段落按句末标点切分
→ 超长句子按字符硬切
→ 使用 overlap 保持上下文连续
```

本任务只实现 `RecursiveChunker`。

以下属于 Day 2，不在当前任务范围：

- `MarkdownHeadingChunker`
- `PDFPageAwareChunker`

---

## 范围

完成以下内容：

1. 创建：
   - `backend/src/rag/chunking/recursive.py`
   - `backend/src/rag/chunking/factory.py`
2. 实现可配置参数：
   - `chunk_size`
   - `chunk_overlap`
3. 默认值建议：
   - `chunk_size=800`
   - `chunk_overlap=100`
4. 按以下层级递归切分：
   - 空行或段落；
   - 中文和英文句末标点；
   - 字符硬切。
5. 为每个 Chunk 填充：
   - 稳定 `chunk_id`
   - `document_id`
   - `text`
   - `chunk_index`
   - `source`
   - `source_type`
   - `page`
   - `section`
   - `heading_path`
   - `chunk_strategy="recursive"`
   - `content_hash`
6. PDF 在页面内部切分，不允许一个 Chunk 跨越多个页码。
7. Factory 当前只支持 `recursive`。
8. 编写 Chunker 单元测试。

---

## 约束

1. `chunk_overlap` 必须小于 `chunk_size`。
2. 非法参数必须抛出明确异常。
3. 不生成空 Chunk。
4. `chunk_index` 在一份文档内从 0 连续递增。
5. `content_hash` 使用规范化 Chunk 文本的 SHA-256。
6. `chunk_id` 必须稳定，至少由以下信息决定：
   - `document_id`
   - `chunk_strategy`
   - `page`
   - `chunk_index`
   - Chunk 文本
7. 相同文档、相同参数重复切分时，Chunk ID 和顺序必须一致。
8. PDF Chunk 必须保留对应页码。
9. Markdown Chunk 必须保留来源文件名。
10. 不实现：
    - Markdown 标题边界切分；
    - PDF 相邻页面合并；
    - LLM 语义切分；
    - Embedding；
    - Chroma。

---

## 验证方式

执行：

```bash
cd backend
uv run pytest tests/test_chunkers.py -q
```

测试至少覆盖：

- 短文本生成一个 Chunk；
- 长段落可按句子切分；
- 超长句子可硬切；
- 不生成空文本；
- overlap 生效；
- 非法参数被拒绝；
- PDF 两页内容生成的 Chunk 保留正确页码；
- Markdown Chunk 保留来源；
- 重复运行产生相同 Chunk ID；
- `chunk_index` 连续；
- Factory 可创建 `recursive`；
- Factory 对未知策略抛出明确异常。

---

## 最终交付

- `backend/src/rag/chunking/recursive.py`
- `backend/src/rag/chunking/factory.py`
- `backend/tests/test_chunkers.py`
- AnyKB 参考或独立实现说明
- 完成报告，包含：
  - 修改文件列表；
  - 核心切分算法说明；
  - 验证命令；
  - 测试结果；
  - 已知限制或设计取舍。
