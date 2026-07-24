# D6-05：文档上传、内置知识库加载与统计接口

## 目标

实现浏览器 Demo 所需的文档 API：上传 PDF/Markdown、加载项目内置知识库，并返回文档/Chunk 统计。上传成功后必须保证 Chroma 与 BM25 均已更新，用户可以立即提问。

## 上下文

技术规格要求：

```http
POST /api/documents/upload
POST /api/documents/load-default
```

上传参数：`file`、`knowledge_base_id`、`chunk_strategy`。响应至少包含 `document_id`、`filename`、`chunks_count`、`status`。

Streamlit 左侧栏还需要显示文档数量和 Chunk 数量，因此本任务允许增加一个最小只读统计端点，例如：

```http
GET /api/documents/stats
```

Day5 审查要求并发入库时不能出现 Chroma 已更新但 BM25 静默陈旧；D6-02 已提供一致性与状态契约，本任务必须复用它。

## 范围

### 1. API Schema

定义请求/响应模型，至少包括：

- Upload 成功响应；
- Load-default 批次响应；
- 文档与 Chunk 统计；
- 部分失败/降级状态；
- 标准错误响应。

MVP 仍是单知识库。`knowledge_base_id` 必须接收并校验，但不得借机实现多租户、多 Collection 管理。可以只接受配置中的默认知识库 ID，对其他值返回明确错误。

### 2. `POST /api/documents/upload`

实现：

- 支持 `.pdf`、`.md`、`.markdown`；
- 校验扩展名、MIME 仅作为辅助，不能只信任客户端 MIME；
- 校验空文件和最大文件大小；
- 安全处理文件名，防止路径穿越；
- 使用受控临时文件或字节流，处理后清理；
- 校验 chunk strategy 与文档类型兼容；
- 调用唯一 Ingestion Service；
- 等待 BM25 最新快照发布后再返回完整成功；
- 重复上传保持现有幂等语义；
- 失败时返回稳定错误码和 request ID。

建议状态：

- `done`：Chroma 与 BM25 均完成；
- `degraded`：如允许 Dense-only，必须明确 BM25 未就绪；
- `failed`：请求未完成。

不要无条件把部分成功标为 `done`。

### 3. `POST /api/documents/load-default`

实现：

- 扫描配置的 `knowledge/markdown` 与 `knowledge/pdf`；
- 只处理支持格式；
- 对已入库内容幂等跳过或 upsert；
- 支持指定/自动匹配 chunk strategy；
- 汇总 `processed`、`skipped`、`failed`、`chunks_count`；
- 单个文件失败不能让结果看起来全部成功；
- 保证批次完成后 BM25 与 Chroma 一致。

是否首次启动自动加载必须由显式配置控制，默认不要在 import 时自动执行。

### 4. `GET /api/documents/stats`

返回至少：

- 文档数量；
- Chunk 数量；
- 当前知识库 ID；
- BM25 generation / status；
- Chroma status。

统计不能依赖遍历上传目录猜测，必须以索引/存储真实状态为准。

### 5. 错误场景

必须覆盖技术规格列出的：

- 空文件；
- 不支持扩展名；
- PDF 无文本；
- 文件过大；
- chunk strategy 不兼容；
- Embedding 失败；
- Chroma 写入失败；
- BM25 rebuild 失败；
- 内置知识目录不存在；
- 重复入库。

### 6. 测试

使用 FastAPI TestClient/AsyncClient 和可注入 Fake Runtime。至少包含：

1. Markdown 上传成功；
2. PDF 上传成功并保留页码来源；
3. 上传返回后立即检索能命中新文档；
4. 并发上传后 stats 与 BM25/Chroma 一致；
5. 空文件/非法扩展名/过大文件；
6. PDF 无文本；
7. load-default 首次处理和第二次幂等；
8. load-default 部分失败汇总；
9. 部分索引失败不返回普通 `done`；
10. 临时文件被清理；
11. 错误响应不泄露服务端路径或异常栈。

## 约束

- 不实现文件删除、重命名、复杂文件管理或多知识库 CRUD。
- 不实现 OCR、扫描 PDF、表格/图片解析。
- 不在路由函数中直接构造 Parser、Chunker、Embedding、Chroma 或 BM25。
- 不让 API 自行重建第二套 runtime。
- 不实现 Streamlit；只提供后端契约。
- 不提前实现 Day7 Docker/Evaluation。

## 验证方式

至少执行：

```bash
cd backend
uv run pytest -q tests/test_api_documents.py
uv run pytest -q tests/test_ingestion.py
uv run pytest -q
```

手工 Smoke：

```bash
curl -F "file=@knowledge/markdown/<sample>.md" \
     -F "knowledge_base_id=technical_docs" \
     -F "chunk_strategy=markdown_heading" \
     http://localhost:8000/api/documents/upload

curl -X POST http://localhost:8000/api/documents/load-default
curl http://localhost:8000/api/documents/stats
```

人工验收：

1. 上传后立即调用检索服务，确认新 Chunk 同时可被 Dense/BM25 使用；
2. 第二次加载内置知识库不无限增加 Chunk；
3. BM25 rebuild 注入失败时响应不是普通成功；
4. PDF 来源包含页码，Markdown 来源包含章节。

## 最终交付

Codex 最终答复必须包含：

1. 三个端点及其请求/响应示例；
2. 文件校验和安全处理说明；
3. 完整成功、降级、失败的状态语义；
4. 改动文件列表；
5. 自动化测试与手工 Smoke 结果；
6. 临时文件/幂等/并发处理说明；
7. 新增 `docs/day6_task05_acceptance.md`。
