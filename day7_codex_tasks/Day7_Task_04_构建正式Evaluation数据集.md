# Day 7 Task 04：构建正式 Evaluation 数据集

## 目标

基于仓库中实际可入库的技术文档，创建 20–30 条可追溯、可验证、覆盖不同查询类型的 Evaluation 数据，并提供 schema 校验和标签一致性检查。

数据集必须能支持 Day7 的 A/B/C/D 四组实验，而不是使用 Day4/Day5 的人工 Fake 排名案例替代正式评估。

## 上下文

技术文档要求 `evaluation/dataset.jsonl` 至少包含：

```json
{
  "id": "q001",
  "question": "...",
  "expected_answer_keywords": ["..."],
  "relevant_chunk_ids": ["..."],
  "source": "...",
  "category": "fact"
}
```

Day7 需要比较：

- A：Recursive + Dense + No Rerank；
- B：Optimized + Dense + No Rerank；
- C：Optimized + Dense + BM25 + RRF + No Rerank；
- D：Optimized + Dense + BM25 + RRF + Rerank。

由于 Recursive 与 Optimized 会生成不同 Chunk ID，数据集不能只靠一组不可迁移的 Chunk ID 硬编码。需要在不破坏技术文档基本 schema 的前提下建立可复现的证据定位和策略映射。

## 范围

### 必须实现

1. 审查 `knowledge/markdown`、`knowledge/pdf` 或当前实际内置知识库文件，只从真实内容创建问题和标签。
2. 创建 20–30 条样本，建议 24 条，覆盖至少以下类别：
   - `fact`：直接事实；
   - `procedure`：步骤/配置方法；
   - `identifier`：函数名、配置键、模型名等关键词型问题；
   - `comparison`：文档中明确存在的对比；
   - `multi_chunk`：答案需要多个 Chunk；
   - `citation`：必须精确到 PDF 页码或 Markdown 章节。
3. 每条样本至少包含：
   - `id`
   - `question`
   - `expected_answer_keywords`
   - `source`
   - `category`
   - `relevant_chunk_ids`（默认/优化策略）
4. 为跨 Chunk 策略评估增加可追溯证据定位，建议字段：
   - `evidence`：source、page、section、heading_path、quote 或 content hash；
   - `relevant_chunk_ids_by_strategy`：如 `recursive`、`markdown_heading`、`pdf_page_aware`。
5. 如果采用运行时解析 evidence 再生成策略对应 Chunk ID：
   - 提供确定性 resolver/build 脚本；
   - 生成后的 resolved dataset 必须可保存并审计；
   - 不得用问题文本本身检索后自动把 Top-K 当标签。
6. 提供 Pydantic/dataclass/schema 校验器或独立验证脚本，检查：
   - ID 唯一；
   - 样本数在 20–30；
   - 关键词非空且去重；
   - source 文件存在；
   - evidence 可定位；
   - relevant chunk IDs 在对应索引中真实存在；
   - category 在允许集合内；
   - JSONL 每行可独立解析。
7. 数据集问题应同时包含中文自然语言、技术标识符和指代被补全后的独立问题，但正式检索 question 本身必须可独立理解。
8. 为每条样本保存简短人工标注说明，放在可选字段或单独 annotation 文档中，说明为什么这些 Chunk 相关。
9. 增加 dataset validator 测试。

### 数据质量要求

- 不得根据当前检索结果“反向挑选容易命中的问题”；
- 不得为了提高指标删除失败样本；
- 多 Chunk 问题的相关 Chunk 集必须完整；
- 关键词只包含答案中应出现的核心事实，不应把停用词或问题原词大量塞入；
- PDF 页码、Markdown 标题和 source 必须能人工复核；
- 样本分布不能全部是精确关键词问题。

### 不包含

- 不实现指标计算；
- 不运行 A/B/C/D；
- 不调用 LLM 自动生成最终标签；
- 不把真实外部模型是否可用作为本任务前提；
- 不新增无关知识库文档，除非当前文档数量不足以支持 20 条高质量样本；若确需新增，必须说明来源和许可。

## 约束

1. 数据集必须完全基于仓库可审计文档，不能凭模型常识补充文档中没有的答案。
2. `relevant_chunk_ids` 与 evidence 不得由被评估的同一 Retriever 自动决定。
3. Chunk ID 若依赖 content hash，应保证重复构建稳定；若现有 Chunk ID 不稳定，必须在任务报告中指出并采用 evidence resolver。
4. 不得包含密钥、内部路径或个人信息。
5. 不允许使用 Day4/Day5 人工 Dense 排名 fixture 作为正式标签或正式结果。

## 验证方式

### 必须通过

1. 数据集行数为 20–30；
2. schema validator 全部通过；
3. 每个 source 文件存在；
4. 每条 evidence 可人工定位；
5. 对至少两种 Chunk 策略生成/验证 relevant Chunk IDs；
6. 重复运行 resolver 结果一致；
7. 至少 5 条 identifier/关键词问题；
8. 至少 5 条需要结构化切分优势的问题；
9. 至少 3 条 multi-chunk 问题；
10. PDF 和 Markdown 均有覆盖。

### 建议命令

```bash
cd backend
uv run python ../evaluation/validate_dataset.py ../evaluation/dataset.jsonl
uv run pytest -q tests/test_evaluation_dataset.py
uv run pytest -q
```

## 最终交付

1. `evaluation/dataset.jsonl`，20–30 条正式样本；
2. 数据集 schema/模型；
3. evidence → strategy chunk IDs 的 resolver 或生成脚本；
4. 数据集校验脚本；
5. 数据集测试；
6. `evaluation/DATASET.md`，说明来源、类别分布、标注方法、已知偏差和版本；
7. 一份完成报告，列出实际样本数量、文档覆盖和人工复核方式。
