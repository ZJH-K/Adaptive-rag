# D5-02 Reranker Adapter Report

## 修改文件

- `backend/src/config.py`：新增 Reranker 开关、服务、模型、超时和 Top-N 配置。
- `.env.example`：补充对应环境变量示例。
- `backend/src/rag/retrieval/reranker.py`：新增抽象契约、HTTP Client、Adapter、No-op 和工厂。
- `backend/src/rag/retrieval/__init__.py`：导出 Reranker 公共类型和异常。
- `backend/tests/test_reranker.py`：新增完整离线单元测试。
- `backend/tests/test_config.py`：覆盖 Reranker 默认值、环境覆盖和数值约束。

## 接口契约

### Provider Client

```python
RerankerClient.score(
    query: str,
    documents: list[str],
) -> list[RerankScore]
```

- 一个请求批量提交全部 query-document pairs；
- `RerankScore` 只暴露经过校验的 `index` 和 `score`；
- 输入文档为空时不读取 API key、不发送请求；
- Provider 原始响应不会传播到上层。

### Reranker Adapter

```python
Reranker.rerank(
    query: str,
    hits: list[SearchHit],
) -> list[SearchHit]
```

- 输出为新列表和深拷贝的 `SearchHit`；
- 只更新 `rerank_score`；
- 保留 metadata、`dense_score`、`bm25_score` 和 `fused_score`；
- 按模型分数降序排序，同分时按候选原始位置稳定排序；
- 最后应用 `top_k` 截断；
- 空候选不会调用 Client。

### 禁用模式

`build_reranker()` 在 `RERANKER_ENABLED=false` 时返回 `NoOpReranker`。No-op 不构造或调用外部 Client，并返回保持原顺序的独立 SearchHit 副本。禁用判断集中在装配工厂，没有散落到业务逻辑。

## Provider 请求与响应

默认请求地址：

```text
{RERANKER_BASE_URL}/rerank
```

默认请求体：

```json
{
  "model": "BAAI/bge-reranker-v2-m3",
  "query": "...",
  "documents": ["..."],
  "top_n": 5,
  "return_documents": false
}
```

实现遵循 [SiliconFlow Create rerank 官方契约](https://docs.siliconflow.cn/en/api-reference/rerank/create-rerank)：官方结果字段 `relevance_score` 被归一为内部 `score`。为兼容使用 `score` 字段的简单 OpenAI-style 网关，也接受二者之一；若同时存在则拒绝，避免字段含义不明确。

响应校验包括：

- `results` 必须是列表；
- index 必须为非布尔整数且在候选范围内；
- index 不得重复，并必须完整覆盖所有输入候选；
- score 必须是有限数值；
- 空响应、无效 UTF-8、非法 JSON 和错误响应形状均显式失败。

## 异常类型

- `RerankerError`：统一基类；
- `RerankerConfigurationError`：URL、模型、API key、超时或 Top-K 配置错误；
- `RerankerInputError`：空 query 或空候选文本；
- `RerankerRequestError`：timeout、HTTP 或 transport 调用失败；
- `RerankerResponseError`：Provider 响应格式、索引或分数不合法。

请求异常仅包含异常类型，不包含 Provider 原始错误文本，因此不会泄露 API key 或完整候选文档。

## 配置

```env
RERANKER_ENABLED=true
RERANKER_BASE_URL=https://api.siliconflow.cn/v1
RERANKER_API_KEY=
RERANKER_MODEL=BAAI/bge-reranker-v2-m3
RERANKER_TIMEOUT_SECONDS=30.0
RERANK_TOP_K=5
```

`RERANK_TOP_K` 是 Adapter 和 Pipeline 共用的最终输出上限。该字段在 D5-03 集成时由原 D5-02 的 `RERANKER_TOP_N` 明确升级而来。

## 测试结果

专项测试：

```bash
cd backend
uv run pytest tests/test_reranker.py tests/test_config.py -q
```

结果：`37 passed in 8.77s`

全量回归：

```bash
cd backend
uv run pytest -q
```

结果：`347 passed, 1 skipped in 65.08s`。跳过项为原有显式 opt-in 的外部 LLM Smoke；Reranker 测试全部使用 Fake Client/Transport，没有外部 API 调用。

附加验证：`python -m compileall -q src tests` 通过。

## 与现有契约的关系

- 继续使用唯一公开结果模型 `SearchHit`；
- 统一保留字段名 `fused_score`，未引入 `rrf_score`；
- 未修改 Agent、Hybrid Retrieval Pipeline、ContextBuilder 或 LangGraph；
- 未实现失败降级，失败降级属于 D5-03 Pipeline 编排职责。

## 未覆盖的 Provider 差异

- 未实现 Provider 专属重试、限流退避或 trace header 提取；
- 未发送 SiliconFlow 可选的 `max_chunks_per_doc`、`overlap_tokens` 或模型 instruction；
- 仅支持文本候选，不支持图片、视频或复杂 document 对象；
- 假定服务在 `top_n` 等于候选数时返回每个候选的完整 score；若某个网关只返回截断结果，会被严格识别为缺失项；
- 未执行真实 SiliconFlow Smoke，真实凭证和服务可用性留给后续显式 opt-in 验收。

## AnyKB 说明

本实现依据本项目契约和 Provider 官方 API 重新设计，没有复制 AnyKB 源码、依赖或多用户基础设施。
