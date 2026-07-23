# D4-04：实现 BM25 Retriever 并统一 SearchHit 输出

## 任务定位

本任务只负责把 D4-03 的 tokenizer/index 封装为可查询的 BM25 Retriever，并返回项目统一的 `SearchHit`。不实现 RRF，不接入 Hybrid Pipeline。

## 目标

1. 实现 `BM25Retriever`；
2. 查询时使用与建索引一致的 Tokenizer；
3. 返回统一 `list[SearchHit]`；
4. 正确保留 `bm25_score`、Chunk 文本和元数据；
5. 对空索引、空查询、Top-N 边界和无结果安全返回。

## 上下文

项目技术文档要求不同检索器返回相同数据结构，并在 SearchHit 中保留 Dense、BM25、Fused、Rerank 分数。Day 3 审查也明确：Day 4 应把 Hybrid Retrieval 封装为同一 `retrieve(query)` 接口，Agent 不应感知 Dense/BM25 细节。

本任务只建立 BM25 检索器本身，为 D4-05/D4-06 提供输入。

## 范围

### 必须完成

1. 阅读并复用：
   - `SearchHit`；
   - `Chunk`；
   - D4-03 Tokenizer 和 BM25 索引接口；
   - 当前 Dense Retriever 的代码风格和 Protocol。
2. 实现 BM25 查询：
   - 输入 query 和 top_n；
   - 使用统一 tokenizer；
   - 调用 `rank_bm25` 得分；
   - 按得分稳定降序排序；
   - 返回最多 top_n 个结果。
3. 每个结果必须：
   - `chunk_id` 正确；
   - `text` 正确；
   - 完整保留后续引用所需 metadata；
   - 设置 `bm25_score`；
   - 其他尚未产生的 score 保持 `None`；
   - 不修改原始 Chunk。
4. 定义并测试相同分数时的确定性排序规则；
5. 定义并测试以下边界：
   - 空 query；
   - 仅标点 query；
   - 空索引；
   - top_n <= 0；
   - top_n 大于语料数量；
   - 全部得分为 0；
   - 专有名词、函数名、变量名检索。
6. 若现有 Retriever Protocol 是同步 `retrieve(query)`，保持兼容；若存在 async 风格，不自行引入第二种调用方式。
7. 添加最低限度的 docstring，说明分数语义和排序方向。

### 允许修改

- `backend/src/rag/retrieval/bm25.py`；
- D4-03 索引/Tokenizer 的必要小修；
- `backend/src/rag/schemas.py` 中仅与统一 `SearchHit` 必要的兼容修改；
- 对应测试。

### 不在范围内

- RRF Fusion；
- Hybrid Retrieval Pipeline；
- Agent/LangGraph 节点修改；
- Ingestion 大改；
- 索引持久化；
- Reranker；
- Langfuse。

## 约束

1. 必须返回现有统一 `SearchHit`，不得创建 `BM25Hit` 平行模型；
2. 不把 BM25 原始分数归一化成 Dense 分数尺度；
3. 不通过直接加权分数和 Dense 融合；
4. 查询 tokenizer 必须与建索引 tokenizer 一致；
5. 同分排序必须确定性，避免测试和实验结果漂移；
6. 无结果或单条路径失败语义应简单明确，不抛出无意义异常；
7. 不提前实现 D4-05/D4-06。

## 验证方式

### 专项测试

```bash
uv run pytest -q backend/tests/test_bm25_retriever.py
```

### 全量回归

```bash
uv run pytest -q
```

### 关键词型样例

构造包含以下精确术语的多个 Chunk：

- `thread_id`；
- `similarity_search`；
- `RRF`；
- `BAAI/bge-m3`。

至少验证：

- 精确术语对应 Chunk 排名靠前；
- 返回结果 `bm25_score` 非空；
- 未产生 `dense_score` 和 `fused_score`；
- metadata 可支持文件、页码或章节引用。

## 最终交付

1. BM25 Retriever 实现；
2. 统一 SearchHit 输出；
3. 单元测试；
4. 改动文件清单；
5. 测试命令与结果；
6. 说明零分结果的处理策略；
7. 说明同分排序规则；
8. 记录已知限制；
9. 不提交 RRF 或 Hybrid 集成代码。
