# Day 1 Task 04：实现 OpenAI-compatible Embedding Client

## 开始前必须阅读

### 项目设计文档

必须阅读：

```text
adaptive_rag_project_technical_spec.md
```

重点查看：

- 第 5.3 节 RAG 技术选型；
- 第 6.2 节 Embedding 配置；
- 第 8 节目录结构；
- 第 19 节 Day 1 Embedding 任务；
- 第 21 节 Embedding API 失败场景。

### 开发规则

必须阅读并遵守：

```text
AGENTS.md
```

### AnyKB 仓库

本任务不需要查看 AnyKB。

原因：

- 本项目只需要轻量的 OpenAI-compatible Client；
- 技术文档明确要求重新实现 `rag/embeddings/client.py`；
- 避免带入 AnyKB 的多用户配置和额外基础设施。

---

## 目标

实现可通过 SiliconFlow 等 OpenAI-compatible 服务调用 BGE-M3 的 Embedding Client，为文档 Chunk 和查询生成向量。

---

## 上下文

项目生成模型和向量模型分离。

目标配置示例：

```env
EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
EMBEDDING_API_KEY=your_embedding_api_key
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_DIMENSION=1024
```

Client 后续同时服务于：

- 文档入库；
- Dense Retrieval。

---

## 范围

完成以下内容：

1. 创建：
   - `backend/src/rag/embeddings/client.py`
2. 实现 `EmbeddingClient`。
3. 支持通过构造参数或 Settings 注入：
   - Base URL
   - API Key
   - Model
   - Dimension
   - Batch Size
   - Timeout
4. 实现：
   - `embed_documents(texts: list[str]) -> list[list[float]]`
   - `embed_query(text: str) -> list[float]`
5. 文档 Embedding 支持按 Batch Size 分批调用。
6. 保证返回顺序与输入文本顺序一致。
7. 创建明确异常类型，例如：
   - `EmbeddingConfigurationError`
   - `EmbeddingRequestError`
   - `EmbeddingResponseError`
8. 支持注入底层 API Client，便于测试。
9. 编写不访问真实网络的单元测试。

---

## 约束

1. 空文本列表返回空列表，不调用 API。
2. 单个空查询必须抛出明确参数异常。
3. API Key 缺失时，在真正调用 Embedding 方法时抛出配置异常。
4. API 返回数量与输入数量不一致时必须抛出异常。
5. 配置了 `EMBEDDING_DIMENSION` 时必须校验返回向量维度。
6. 测试不得访问 SiliconFlow 或其他真实服务。
7. 不实现：
   - 缓存；
   - 任务队列；
   - 并发调度器；
   - 限流系统；
   - 复杂重试策略。
8. Embedding Client 不管理 Chroma。
9. 不在日志或异常中输出 API Key。
10. 不在本任务中实现 Ingestion Pipeline 或 Retriever。

---

## 验证方式

执行：

```bash
cd backend
uv run pytest tests/test_embedding_client.py -q
```

测试至少覆盖：

- 单个 Query Embedding；
- 多条文档 Embedding；
- 超过 Batch Size 后正确分批；
- 输入输出顺序一致；
- 空列表；
- 空查询；
- API Key 缺失；
- API 请求异常；
- 返回数量不匹配；
- 向量维度不匹配；
- API Key 不出现在日志或异常文本中。

---

## 最终交付

- `backend/src/rag/embeddings/client.py`
- Embedding 自定义异常
- `backend/tests/test_embedding_client.py`
- Mock 或 Fake API Client
- 完成报告，包含：
  - 修改文件列表；
  - Client 设计说明；
  - 验证命令；
  - 测试结果；
  - 遗留问题或设计取舍。
