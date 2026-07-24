# D4-03：实现中文 Tokenizer 与 BM25 索引基础设施

## 任务定位

这是 Day 4 的第一项正式功能任务。只负责把现有 Chunk 转换为可检索的 BM25 语料和索引，不实现 BM25 Retriever、不接入 LangGraph、不实现 RRF。

## 目标

1. 实现可替换、可测试的中文 Tokenizer；
2. 基于统一 `Chunk` 数据结构构建 BM25 索引；
3. 建立索引与原始 Chunk 的稳定映射；
4. 支持空语料、重复 Chunk、重建索引等边界；
5. 为后续 BM25 Retriever 提供清晰接口。

## 上下文

技术文档要求 Day 4 使用：

```text
Query → Tokenize → rank_bm25 → Top 20
```

并指出简单字符或空格策略只适合作为第一版，中文 BM25 推荐尽快加入 `jieba`。项目已有 `Chunk`、Ingestion Pipeline、Chroma 和 Dense Retrieval，Day 4 应复用现有 Chunk 元数据，不建立第二套文档模型。

## 范围

### 必须完成

1. 检查当前 `pyproject.toml` 和依赖管理方式；
2. 选择轻量中文 Tokenizer 方案：
   - 优先使用 `jieba`；
   - 封装为 Protocol/类/函数，使测试可以注入简单 tokenizer；
   - 英文、数字、下划线、连字符、点号形式的技术词尽量保持可检索性，例如 `thread_id`、`similarity_search`、`LangGraph`、`v2-m3`；
   - 统一大小写、空白和空 token 处理规则。
3. 新增 BM25 索引对象，至少保存：
   - tokenized corpus；
   - 与 corpus 下标对应的 `Chunk` 或 `chunk_id` 映射；
   - 索引构建版本/状态所需的最小信息。
4. 支持从 `list[Chunk]` 构建或重建索引；
5. 对重复 `chunk_id` 定义明确行为：拒绝、去重或后者覆盖，必须有测试和说明；
6. 空语料构建不得崩溃，后续查询应可返回空结果；
7. 若当前 Ingestion 已有“重建或更新 BM25 索引”扩展点，可接入最小生命周期；若没有，只提供独立索引构建 API，不提前大改 Ingestion；
8. 增加测试覆盖：
   - 中文句子；
   - 中英混合技术文本；
   - 函数名/变量名/版本号；
   - 标点与空白；
   - 空文本；
   - 空语料；
   - 重复 chunk ID；
   - 重建后映射正确。

### 建议新增文件

根据现有目录风格选择，通常包括：

- `backend/src/rag/retrieval/tokenizer.py`；
- `backend/src/rag/retrieval/bm25_index.py` 或合并到后续 `bm25.py`；
- 对应测试文件。

### 不在范围内

- 返回 `SearchHit` 的 BM25 Retriever；
- RRF；
- Dense/BM25 并行执行；
- LangGraph 集成；
- 索引持久化到外部数据库；
- Elasticsearch；
- Reranker；
- 完整 Evaluation。

## 约束

1. 复用现有 `Chunk`，不得创建平行 Chunk 模型；
2. Tokenizer 与 BM25 索引必须可独立测试；
3. 默认测试不能依赖网络；
4. 不把 tokenizer 逻辑写死在 Retriever 查询函数中；
5. 不实现复杂 NLP 预处理、同义词扩展或停用词系统；
6. 依赖新增必须写入 `pyproject.toml` 并通过 `uv sync`；
7. 不破坏现有 Chroma/Dense 入库链路。

## 验证方式

### 依赖与静态验证

```bash
uv sync
```

### 专项测试

```bash
uv run pytest -q backend/tests/test_tokenizer.py backend/tests/test_bm25_index.py
```

文件名可按仓库实际调整。

### 全量回归

```bash
uv run pytest -q
```

### 必须验证的样例

至少证明下列文本能产生符合预期的 tokens：

```text
LangGraph 使用 thread_id 配置 checkpoint。
调用 Chroma similarity_search 返回 Top-K 结果。
BAAI/bge-reranker-v2-m3 用于重排。
```

并证明索引位置 `i` 可稳定映射回正确 `chunk_id`。

## 最终交付

1. Tokenizer 实现；
2. BM25 索引构建实现；
3. 新增依赖及锁文件更新；
4. 单元测试；
5. 改动文件清单；
6. 测试命令与结果；
7. 说明 token 规范化规则；
8. 说明索引更新/重建策略；
9. 记录已知中文分词限制；
10. 不提交 Retriever、RRF 或 LangGraph 集成代码。
