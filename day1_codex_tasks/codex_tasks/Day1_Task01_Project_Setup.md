# Day 1 Task 01：初始化后端工程、配置系统与核心数据模型

## 开始前必须阅读

### 项目设计文档

必须阅读：

```text
adaptive_rag_project_technical_spec.md
```

重点查看：

- 第 5 节技术选型；
- 第 6 节模型与服务配置；
- 第 8 节项目目录；
- 第 9 节核心数据结构；
- 第 19 节 Day 1 计划；
- 第 20、21 节范围与测试要求。

### 开发规则

必须阅读并遵守：

```text
AGENTS.md
```

### AnyKB 仓库

本任务不需要查看 AnyKB。

原因：本任务只负责项目基础设施、配置和数据契约，不涉及 AnyKB 代码复用。

---

## 目标

建立 Day 1 后续代码可以依赖的后端工程骨架，完成依赖管理、环境配置和核心 RAG 数据结构定义。

---

## 上下文

本项目是一个以 RAG 为核心的技术文档问答系统。Day 1 后续 Parser、Chunker、Embedding、Chroma 和 Retrieval 都必须围绕统一的数据结构工作。

项目要求：

- Python 3.11+；
- 使用 `uv` 管理依赖；
- 使用 Pydantic v2 定义模型；
- 使用 Pydantic Settings 管理配置；
- 使用 `backend/src/` 作为源码目录；
- 使用 pytest 进行测试。

---

## 范围

完成以下内容：

1. 创建后端基础目录：
   - `backend/src/`
   - `backend/src/rag/`
   - `backend/src/rag/parsers/`
   - `backend/src/rag/chunking/`
   - `backend/src/rag/embeddings/`
   - `backend/src/rag/vectorstore/`
   - `backend/src/rag/ingestion/`
   - `backend/src/rag/retrieval/`
   - `backend/tests/`
2. 补充必要的 `__init__.py`。
3. 创建 `backend/pyproject.toml`。
4. 配置 Day 1 运行依赖：
   - `pydantic`
   - `pydantic-settings`
   - `pymupdf`
   - `chromadb`
   - `openai` 或等价 OpenAI-compatible 客户端
5. 配置开发依赖：
   - `pytest`
   - `pytest-cov`
6. 创建 `backend/src/config.py`，至少支持：
   - `EMBEDDING_BASE_URL`
   - `EMBEDDING_API_KEY`
   - `EMBEDDING_MODEL`
   - `EMBEDDING_DIMENSION`
   - `EMBEDDING_BATCH_SIZE`
   - `EMBEDDING_TIMEOUT_SECONDS`
   - `CHROMA_PERSIST_DIR`
   - `CHROMA_COLLECTION`
7. 在项目根目录创建 `.env.example`。
8. 创建 `backend/src/rag/schemas.py`，定义：
   - `ParsedDocument`
   - `ParsedPage`
   - `Chunk`
   - `SearchHit`
9. 创建最小 `NOTICE.md`，记录项目参考 AnyKB，但不要在未确认许可证前声明已复制源码。
10. 编写 Schema 和 Settings 测试。

---

## 约束

1. Pydantic 模型中的列表和字典必须使用 `Field(default_factory=...)`。
2. `source_type` 限制为 `pdf` 或 `markdown`。
3. `Chunk` 必须包含：
   - `chunk_id`
   - `document_id`
   - `text`
   - `chunk_index`
   - `source`
   - `source_type`
   - `page`
   - `section`
   - `heading_path`
   - `chunk_strategy`
   - `content_hash`
4. `SearchHit` 必须预留：
   - `dense_score`
   - `bm25_score`
   - `fused_score`
   - `rerank_score`
5. `config.py` 导入时不得连接网络或初始化 Chroma。
6. API Key 缺失时 Settings 可以实例化；只有实际调用 Embedding 时才报错。
7. 不创建 FastAPI 应用、API 路由或 LangGraph。
8. 不实现后续任务中的 Parser、Chunker、Embedding 或 Chroma 逻辑。
9. 不提交 `.env` 或任何真实密钥。

---

## 验证方式

执行：

```bash
cd backend
uv sync
uv run python -c "from src.config import Settings; print(Settings().embedding_model)"
uv run python -c "from src.rag.schemas import ParsedDocument, ParsedPage, Chunk, SearchHit; print('schemas ok')"
uv run pytest -q
```

必须验证：

- 依赖正常安装；
- Settings 能读取默认值；
- 环境变量能够覆盖默认值；
- 四个数据模型可正常导入；
- 两个模型实例之间的列表、字典默认值互不影响；
- pytest 全部通过。

---

## 最终交付

- `backend/pyproject.toml`
- `backend/src/config.py`
- `backend/src/rag/schemas.py`
- 必要的包初始化文件
- `.env.example`
- `NOTICE.md`
- Schema 与 Settings 测试
- 完成报告，包含：
  - 修改文件列表；
  - 实现摘要；
  - 验证命令；
  - 验证结果；
  - 遗留问题或设计取舍。
