# Day 1 Task 05：实现 Chroma 持久化 Vector Store

## 开始前必须阅读

### 项目设计文档

必须阅读：

```text
adaptive_rag_project_technical_spec.md
```

重点查看：

- 第 5.3 节 Chroma 技术选型；
- 第 6.4 节 Chroma 配置；
- 第 8 节目录结构；
- 第 9 节 `Chunk` 与 `SearchHit`；
- 第 11.1 节 Dense Retrieval；
- 第 19 节 Day 1 持久化和幂等验收。

### 开发规则

必须阅读并遵守：

```text
AGENTS.md
```

### AnyKB 仓库

本任务不需要查看 AnyKB。

原因：

- 技术文档明确要求 Chroma 模块重写；
- AnyKB 的 Vector Store 不是本项目选定的 Chroma 方案；
- 参考其多后端实现容易引入无关复杂度。

---

## 目标

封装 Chroma 持久化操作，实现 Chunk 的批量写入、幂等更新、向量查询和重启后数据恢复。

---

## 上下文

Day 1 使用 Chroma 作为本地向量数据库。

Vector Store 只负责：

- 存储已有向量；
- 持久化 Chunk 文本与元数据；
- 基于查询向量进行相似度查询。

重复入库不能无限新增 Chunk，因此必须基于稳定 `chunk_id` 使用 `upsert`。

---

## 范围

完成以下内容：

1. 创建：
   - `backend/src/rag/vectorstore/chroma.py`
2. 实现 `ChromaVectorStore`。
3. 使用 `PersistentClient` 和 `CHROMA_PERSIST_DIR`。
4. 使用 `get_or_create_collection`。
5. Collection 使用 cosine 距离。
6. 实现至少以下方法：
   - `upsert_chunks(chunks, embeddings)`
   - `query_by_vector(query_embedding, top_k)`
   - `count()`
   - `get_chunks_by_document_id(document_id)`
   - `contains_document(document_id)`
7. Chunk 文本写入 Chroma documents。
8. 必要 Chunk 字段写入 metadata。
9. 对 `heading_path` 等复杂字段进行安全 JSON 序列化。
10. Chroma 查询结果返回清晰的内部结果结构。
11. 编写持久化和幂等测试。

---

## 约束

1. Chunk 数量和 Embedding 数量不一致时必须拒绝写入。
2. 必须使用 `upsert`，不得使用会产生重复 ID 的写入方式。
3. 不将 API Key 或客户端配置写入 metadata。
4. metadata 只使用 Chroma 支持的标量类型；复杂值需序列化。
5. 查询结果必须保留：
   - Chunk ID
   - 文本
   - metadata
   - distance
6. Vector Store 不负责将 distance 转成业务层 `SearchHit`。
7. Vector Store 不调用 Embedding Client。
8. 测试必须使用 pytest 临时目录。
9. 测试不得污染正式 `data/chroma`。
10. 创建新的 `ChromaVectorStore` 实例后，必须能读取同一路径的已有数据。
11. 不实现 BM25、RRF 或 Rerank。

---

## 验证方式

执行：

```bash
cd backend
uv run pytest tests/test_chroma_vectorstore.py -q
```

测试至少覆盖：

- 批量写入；
- `count()` 正确；
- 向量查询；
- 按 `document_id` 查询；
- `contains_document()`；
- 重复 upsert 不增加总数量；
- metadata 正确保存和恢复；
- 重新创建实例后数据仍存在；
- Chunk 和 Embedding 数量不一致时报错；
- `top_k` 生效。

---

## 最终交付

- `backend/src/rag/vectorstore/chroma.py`
- metadata 序列化与反序列化逻辑
- `backend/tests/test_chroma_vectorstore.py`
- 持久化和幂等性测试
- 完成报告，包含：
  - 修改文件列表；
  - Chroma 封装设计说明；
  - 验证命令；
  - 测试结果；
  - 遗留问题或设计取舍。
