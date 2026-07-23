# Day 7 正式 Evaluation 数据集

本目录保存 Adaptive RAG 的人工证据标注与确定性块 ID 映射。数据集用于后续检索评估，但本任务不运行检索指标，也不使用 Dense、BM25、Fusion 或 Rerank 的 TopK 结果生成标签。

## 文件

- `dataset.source.jsonl`：人工维护的源标注。问题、关键词、来源、证据 quote/page/section/heading_path、类别和标注理由都在这里编辑。
- `dataset.jsonl`：由 resolver 生成的正式数据集，额外包含默认优化策略的 `relevant_chunk_ids`，以及 `relevant_chunk_ids_by_strategy`。
- `models.py`：Pydantic 行级模型和字段约束。
- `resolve_dataset.py`：使用生产 parser 与 chunker，把人工证据确定性映射到实际 chunk ID。
- `validate_dataset.py`：校验格式、覆盖度、来源、证据定位及策略 ID。

`dataset.jsonl` 当前包含 24 条中文问题，覆盖 5 份真实知识文档。类别分布为：fact 4、procedure 4、identifier 6、comparison 4、multi_chunk 3、citation 3；同时覆盖 Markdown 与 PDF，其中 16 条显式标记为结构化切分测试。

## 标注原则

每条问题都可以脱离聊天上下文独立理解。`expected_answer_keywords` 只包含从原文答案可核验的关键表达；技术标识符保持原始拼写。`evidence` 是人工选择的原文片段：Markdown 同时记录 section 和完整 heading_path，PDF 记录解析器产生的一基页码。`annotation_rationale` 说明该证据为何足以支持问题。

块 ID 不是由查询检索结果产生。resolver 对每份来源调用项目正式 parser，再使用默认参数 `chunk_size=800`、`chunk_overlap=100` 构建：

- 所有文档：`recursive` 基线；
- Markdown：`markdown_heading` 优化策略；
- PDF：`pdf_page_aware` 优化策略。

resolver 先按人工 page 或 heading_path 限定位置，再匹配规范化后的 quote。`relevant_chunk_ids` 始终等于该来源优化策略的映射。若原文、解析器或切分参数改变，旧 ID 会由 validator 判定失效，必须重新审阅证据后生成。

## 生成与验证

在 `backend` 目录执行：

```bash
uv run python ../evaluation/resolve_dataset.py \
  ../evaluation/dataset.source.jsonl ../evaluation/dataset.jsonl
uv run python ../evaluation/validate_dataset.py ../evaluation/dataset.jsonl
uv run pytest -q tests/test_evaluation_dataset.py
```

测试会将源标注独立解析两次，并与提交的 `dataset.jsonl` 做字节级比较，从而验证 resolver 与三种 chunk ID 规则的确定性。validator 还会检查：20–30 条规模、ID 唯一、关键词非空且去重、六类覆盖、来源真实存在、证据可定位、每个策略 ID 实际存在、至少 5 条 identifier、至少 3 条 multi_chunk、至少 5 条结构化切分问题，以及 PDF/Markdown 双格式覆盖。

## 版本与已知偏差

当前数据集版本为 `day7-task04-v1`（2026-07-23）。它绑定当前仓库内 5 份知识文档的文件内容、生产 parser、生产 chunk ID 算法，以及 `chunk_size=800`、`chunk_overlap=100` 的索引构建契约；这些输入的任何变化都应视为新索引版本，并重新生成与审阅数据集。

当前语料规模较小，且知识原文为英文、问题主要为中文，因此该集合更适合回归比较，不代表开放域或纯中文语料表现。PDF 每页文本均短于默认 chunk size，`recursive` 与 `pdf_page_aware` 当前会保持相同页边界但生成不同策略 ID；PDF 样本主要检验页级溯源和跨页完整性。关键词评分只能验证核心事实是否出现，不能替代答案忠实度人工评审。这些限制不得通过删除失败样本规避。

## 更新流程

1. 只在 `dataset.source.jsonl` 中新增或修改人工标注，不手改生成的 chunk ID。
2. 对照知识库原文复核 quote 和位置元数据；不得用任何检索器 TopK 作为相关性标签。
3. 运行 resolver，检查生成 diff 中的问题、关键词、证据和 ID 映射。
4. 运行 validator 和专项测试，再运行后端完整测试。
