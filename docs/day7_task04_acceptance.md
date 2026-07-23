# Day 7 Task 04 验收记录

## 交付结果

- 建立 24 条基于真实知识文档的正式 Evaluation JSONL 数据集。
- 覆盖 fact、procedure、identifier、comparison、multi_chunk、citation 六类问题，以及 Markdown/PDF 两种来源。
- 保存人工证据位置、原文 quote、答案关键词、标注理由和结构化切分测试标记。
- 为 recursive、markdown_heading、pdf_page_aware 三种适用策略生成真实、稳定的 chunk ID。
- 提供确定性 resolver、严格 validator、专项自动化测试与维护文档。

## 文档覆盖与人工复核

- `context_citation_guide.md`：5 条；按 Markdown 完整 heading_path 和原文 quote 复核。
- `embedding_batching.md`：6 条；按配置标识符、方法契约和标题层级复核。
- `langgraph_checkpoint.md`：4 条；按 `thread_id` 与配置步骤原文复核。
- `dense_retrieval_guide.pdf`：5 条；逐页抽取文本并渲染 2 页页面复核。
- `ingestion_recovery_manual.pdf`：4 条；逐页抽取文本并渲染 3 页页面复核。

PDF 页码全部来自生产 PDF parser 的一基页码；Markdown section/heading_path 全部来自生产 heading-aware chunker。resolver 在位置过滤后才匹配人工 quote，不读取 question，也不调用 Retriever。

## 标签边界

相关块标签完全来自人工证据定位和生产 parser/chunker 的确定性映射，没有运行或使用任何检索器 TopK 结果。当前任务未提前实现 Recall@K、MRR、Hit Rate 或 A/B/C/D 评估运行。

## 验收命令

```bash
cd backend
uv run python ../evaluation/validate_dataset.py ../evaluation/dataset.jsonl
uv run pytest -q tests/test_evaluation_dataset.py
uv run pytest -q
```

实际结果：validator 通过 24 条；专项测试 6 passed；后端完整回归 481 passed、3 skipped。
