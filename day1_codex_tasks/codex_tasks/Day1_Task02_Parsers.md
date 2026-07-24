# Day 1 Task 02：实现 Markdown/PDF Parser 与 Parser Factory

## 开始前必须阅读

### 项目设计文档

必须阅读：

```text
adaptive_rag_project_technical_spec.md
```

重点查看：

- 第 7 节 AnyKB 复用边界；
- 第 8 节目录结构；
- 第 9 节 `ParsedDocument` 与 `ParsedPage`；
- 第 10 节 Chunk 策略中的文档结构要求；
- 第 19 节 Day 1 Parser 任务；
- 第 21 节 Parser 测试要求。

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
backend/src/kb/parsers/
```

目的：

- 理解 Markdown 清洗逻辑；
- 理解 Parser 模块职责；
- 识别可参考的异常处理和文本规范化方式。

注意：

- 不要直接复制整个 Parser 模块；
- PDF Parser 必须按本项目要求重写并保留页码；
- 不要引入 AnyKB 的数据库、ORM、多租户或知识库对象。

---

## 目标

实现统一的文档解析层，使 Markdown 和数字版 PDF 都能转换为 `ParsedDocument`，并确保 PDF 页码被完整保留。

---

## 上下文

Day 1 入库链路首先需要把不同格式的文件转换成统一结构：

```text
文件
→ ParsedDocument
→ list[ParsedPage]
```

Markdown Parser 可以参考 AnyKB 的清洗思路，但必须返回本项目 Schema。

PDF Parser 必须独立实现页级解析，因为本项目后续引用和检索元数据依赖页码。

---

## 范围

完成以下内容：

1. 创建 Parser 公共协议、接口或抽象基类。
2. 创建统一解析异常，例如：
   - `DocumentParseError`
   - `UnsupportedDocumentTypeError`
3. 实现：
   - `backend/src/rag/parsers/markdown.py`
   - `backend/src/rag/parsers/pdf.py`
   - `backend/src/rag/parsers/factory.py`
4. Markdown Parser：
   - 支持 `.md` 和 `.markdown`；
   - 使用 UTF-8 读取；
   - 清理空字符；
   - 规范异常换行；
   - 保留正文；
   - 可以提取 Markdown 标题文本放入 `ParsedPage.headings`；
   - 返回 `source_type="markdown"`。
5. PDF Parser：
   - 使用 PyMuPDF；
   - 按页解析；
   - 页码从 1 开始；
   - 每个有效页面对应一个 `ParsedPage`；
   - 返回 `source_type="pdf"`。
6. 使用文件内容 SHA-256 生成稳定的 `document_id`。
7. Parser Factory 根据扩展名选择正确 Parser。
8. 编写两个 Parser 和 Factory 的测试。

---

## 约束

1. 不实现 OCR。
2. 不恢复图片、表格和复杂 PDF 布局。
3. PDF Parser 不得把所有页面合并后丢失页码。
4. 空文件必须抛出明确异常。
5. PDF 完全没有可提取文本时必须抛出明确异常。
6. 不支持的扩展名必须由 Factory 抛出明确异常。
7. 相同文件内容重复解析时，`document_id` 必须一致。
8. Parser 只负责解析，不负责：
   - Chunk；
   - Embedding；
   - Chroma；
   - Retrieval。
9. 测试 PDF 由 PyMuPDF 动态生成，避免依赖外部文件。
10. 不实现 Day 2 的结构感知 Chunker。

---

## 验证方式

执行：

```bash
cd backend
uv run pytest tests/test_parsers.py -q
```

测试至少覆盖：

- 正常 Markdown；
- 空 Markdown；
- 正常两页 PDF；
- PDF 页码分别为 1 和 2；
- 无文本 PDF；
- 不支持的扩展名；
- 相同文件重复解析得到相同 `document_id`；
- Markdown 和 PDF 的 `source_type` 正确；
- Markdown 标题提取行为符合预期。

人工检查一个两页 PDF 的解析输出，确认包含：

```text
page_number=1
page_number=2
```

---

## 最终交付

- Parser 公共接口或协议
- Parser 异常类型
- `backend/src/rag/parsers/markdown.py`
- `backend/src/rag/parsers/pdf.py`
- `backend/src/rag/parsers/factory.py`
- `backend/tests/test_parsers.py`
- AnyKB 参考说明和 LICENSE 检查结果
- 完成报告，包含：
  - 修改文件列表；
  - 实现摘要；
  - 验证命令；
  - 测试结果；
  - 遗留问题或设计取舍。
