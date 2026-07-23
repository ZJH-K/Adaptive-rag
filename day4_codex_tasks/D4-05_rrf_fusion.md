# D4-05：实现 Reciprocal Rank Fusion（RRF）

## 任务定位

本任务只实现纯粹的排名融合组件：输入 Dense 和 BM25 的 `SearchHit` 排名列表，输出统一、确定性的融合结果。不得在此任务中接入 LangGraph 或完成整个 Hybrid Pipeline。

## 目标

1. 实现可独立测试的 RRF Fusion；
2. 使用排名而不是直接混合 Dense/BM25 原始分数；
3. 合并相同 `chunk_id`，保留两路原始分数；
4. 计算并保存 `fused_score`；
5. 任一路为空时仍能返回另一条路径的结果；
6. 产生稳定、可解释的排序结果。

## 上下文

技术文档指定公式：

```text
RRF(d) = Σ 1 / (k + rank_i(d))
```

建议 `k = 60`。RRF 的价值是避免 Dense 与 BM25 分数尺度不一致，因此本任务禁止直接加权原始分数。

`SearchHit` 已预留：

- `dense_score`；
- `bm25_score`；
- `fused_score`；
- `rerank_score`。

## 范围

### 必须完成

1. 实现独立函数或类，例如：

```python
fuse(dense_hits, bm25_hits, *, k=60, top_n=None) -> list[SearchHit]
```

具体签名应符合仓库风格。
2. 排名从 1 开始计算；
3. 同一 `chunk_id` 在两路结果中必须合并为一条：
   - 保留 `dense_score`；
   - 保留 `bm25_score`；
   - 计算两路贡献之和；
   - 文本和 metadata 必须一致或按明确规则选择；
   - 若同一 chunk 的文本/关键 metadata 冲突，应抛出清晰错误或采用可审计策略，不能静默拼接。
4. 只出现于单路的 Chunk 也应得到该路的 RRF 贡献；
5. 支持 `top_n` 截断；
6. 对非法 `k`、非法 top_n 定义清晰行为；
7. 同 `fused_score` 时使用确定性 tie-break：优先更好的最佳单路排名，再按稳定字段（如 chunk_id）；具体规则需写入测试和说明；
8. 不修改输入列表和输入 SearchHit；
9. 增加测试覆盖：
   - 两路有交集；
   - 两路完全无交集；
   - Dense 空；
   - BM25 空；
   - 两路都空；
   - 同分；
   - top_n；
   - score 保留；
   - 输入不可变；
   - 公式数值精确验证。

### 建议文件

- `backend/src/rag/retrieval/fusion.py`；
- `backend/tests/test_rrf_fusion.py` 或现有测试命名风格。

### 不在范围内

- 调用 Dense Retriever；
- 调用 BM25 Retriever；
- 配置开关；
- LangGraph/Agent 接入；
- Reranker；
- 分数归一化或学习排序。

## 约束

1. 必须严格按排名计算，不使用原始 score 参与 RRF 公式；
2. 默认 `k` 与技术文档一致为 60，配置化可在 D4-06 完成；
3. 不允许重复 chunk 出现在输出中；
4. 不允许丢失 Dense/BM25 原始分数；
5. 不设置 `rerank_score`；
6. 纯函数优先，避免隐藏全局状态；
7. 结果顺序必须完全确定性。

## 验证方式

### 公式验证

构造：

```text
Dense: A(rank1), B(rank2), C(rank3)
BM25: B(rank1), D(rank2), A(rank3)
```

默认 `k=60` 时至少断言：

```text
A = 1/(60+1) + 1/(60+3)
B = 1/(60+2) + 1/(60+1)
C = 1/(60+3)
D = 1/(60+2)
```

并验证 B 排在 A 前。

### 专项测试

```bash
uv run pytest -q backend/tests/test_rrf_fusion.py
```

### 全量回归

```bash
uv run pytest -q
```

## 最终交付

1. RRF 实现；
2. 完整单元测试；
3. 改动文件清单；
4. 测试命令与结果；
5. 公式与 rank 起点说明；
6. tie-break 规则说明；
7. metadata 冲突处理说明；
8. 不提交 Hybrid Pipeline 或 Agent 集成代码。
