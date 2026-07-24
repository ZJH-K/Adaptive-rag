# Day 1 Task 06：实现最小 Ingestion Pipeline 与 Dense Retriever

## 开始前必须阅读

### 项目设计文档

必须阅读：

```text
adaptive_rag_project_technical_spec.md
```

重点查看：

- 第 4.1 节文档上传与入库链路；
- 第 8 节目录结构；
- 第 9 节核心数据结构；
- 第 11.1 节 Dense Retrieval；
- 第 19 节 Day 1 完整基础链路和验收标准；
- 第 21 节集成测试与错误场景。

### 开发规则

必须阅读并遵守：

```text
AGENTS.md
```

### AnyKB 仓库

本任务可选查看：

```text
https://github.com/GU-Cryptography/anykb
```

如需参考，重点查看：

- `backend/src/kb/ingest.py`
- `backend/src/infra/embedding.py`
- `backend/src/tools/kb_search.py`

目的：

- 理解入库编排职责；
- 理解模块之间的调用边界；
- 参考错误传播和批量处理思路。

注意：

- 不复制数据库、ORM、多租户或 Agent Tool Loop；
- 本项目 Pipeline 必须保持轻量；
- 本任务是否查看 AnyKB 不影响验收。

---

## 目标

把前面完成的 Parser、RecursiveChunker、Embedding Client 和 Chroma 串联起来，形成完整的文档入库链路，并实现最小 Dense Retrieval。

---

## 上下文

当前应已经具备：

```text
Parser
RecursiveChunker
EmbeddingClient
ChromaVectorStore
```

本任务新增两个薄层编排模块：

```text
文件
→ Parser
→ Chunker
→ Embedding
→ Chroma
```

以及：

```text
Query
→ Embedding
→ Chroma Query
→ SearchHit
```

---

## 范围

完成以下内容：

1. 创建：
   - `backend/src/rag/ingestion/pipeline.py`
   - `backend/src/rag/retrieval/dense.py`
2. 实现最小 `IngestionPipeline`：
   - 接收单个文件路径；
   - 使用 Parser Factory；
   - 使用 RecursiveChunker；
   - 批量生成 Embedding；
   - Upsert 到 Chroma；
   - 返回入库结果。
3. 入库结果至少包含：
   - `document_id`
   - `filename`
   - `chunks_count`
   - `status`
4. 实现 `DenseRetriever`：
   - 接收字符串 Query；
   - 调用 `embed_query`；
   - 调用 Chroma 查询；
   - 转换为 `list[SearchHit]`。
5. 使用 cosine distance 生成 `dense_score`：

```text
dense_score = 1 - distance
```

6. 为 Pipeline 和 Retriever 编写单元测试和基础集成测试。
7. 测试使用 Fake Embedding Client，不访问真实 API。

---

## 约束

1. Pipeline 只负责单个文件的同步入库。
2. 不实现：
   - 上传 API；
   - 后台任务；
   - 批量目录扫描；
   - FastAPI；
   - LangGraph；
   - Query Rewrite；
   - Hybrid Retrieval；
   - Context Builder；
   - 答案生成。
3. 重复入库相同文件时：
   - `document_id` 不变；
   - Chunk ID 不变；
   - Chroma 总数不增长。
4. Embedding 调用失败时，不得写入不完整数据。
5. 空文件、无文本 PDF 等 Parser 错误必须向上抛出明确异常。
6. `DenseRetriever.top_k` 必须大于 0。
7. Chroma 无结果时返回空列表。
8. `SearchHit.metadata` 必须包含来源信息。
9. PDF 结果 metadata 必须包含页码。
10. Dense Retriever 不负责生成答案或引用文本。

---

## 验证方式

执行：

```bash
cd backend
uv run pytest tests/test_ingestion.py tests/test_retrieval.py -q
```

测试至少覆盖：

- Markdown 完整入库；
- PDF 完整入库；
- PDF Chunk 页码写入 Chroma；
- Markdown Chunk 来源写入 Chroma；
- 相同文件重复入库；
- Embedding 失败时不产生半成品数据；
- Dense Retrieval 返回 `SearchHit`；
- 检索分数按相关性顺序排列；
- `top_k` 生效；
- 无结果返回空列表；
- 非法 `top_k` 被拒绝。

---

## 最终交付

- `backend/src/rag/ingestion/pipeline.py`
- `backend/src/rag/retrieval/dense.py`
- 入库结果模型或明确返回结构
- `backend/tests/test_ingestion.py`
- `backend/tests/test_retrieval.py`
- Fake Embedding Client
- 完成报告，包含：
  - 修改文件列表；
  - Pipeline 数据流说明；
  - 验证命令；
  - 测试结果；
  - 遗留问题或设计取舍。
