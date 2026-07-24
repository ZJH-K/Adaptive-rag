# Day 7 Task 06 验收记录

## 实现范围

- A/B/C/D 显式 Pydantic 配置与 CLI；
- 每组隔离 Chroma persist path 和 collection；
- 复用生产 Parser、Chunker、Embedding、Chroma、BM25、RRF、Reranker 和 BasicRAGService；
- 逐样本 JSONL、聚合 JSON、Markdown 报告；
- 数据集/知识文件哈希、run ID、UTC 时间、Git revision、Python 和 uv.lock 版本记录；
- Provider 缺失、失败、跳过和 Retrieval 降级的结果诚信处理；
- 无凭据 validate-only 索引计划校验；
- Fake Provider 仅用于 Runner 控制流测试，不写入正式 reports。

## 验收命令

```bash
uv run --project backend python evaluation/run_eval.py --validate-only --all
cd backend
uv run pytest -q tests/test_evaluation_runner.py
uv run pytest -q
```

校验报告位于 `evaluation/reports/day7-task06-validation/`，明确标记 `VALIDATED` 和 `N/A`，没有伪正式指标。

## 真实执行结果

真实报告位于 `evaluation/reports/day7-task06-run/`：

- A：COMPLETED，24/24；Hit@1 0.9167，Recall@5 1.0000，MRR 0.9583；
- B：COMPLETED，24/24；Hit@1 0.8333，Recall@5 0.9792，MRR 0.9167；
- C：COMPLETED，24/24；Hit@1 0.8333，Recall@5 0.9792，MRR 0.9097；
- D：SKIPPED，原因 `reranker_not_configured`，无指标、无 samples_D 文件。

结果没有显示 B/C 优于 A：A→B MRR 为 -0.0417，B→C 为 -0.0069。报告按项目内小数据集如实保留该退化，不修改标签或选择性隐藏运行。

人工复核 q001、q006、q013、q018、q022：A/B/C 的 relevant IDs 均属于对应策略标签，来源覆盖 3 份 Markdown 与 2 份 PDF，相关排名与 JSONL 记录一致。

Runner 专项测试 10 passed；Evaluation 数据集、指标与 Runner 联合测试 39 passed；后端完整回归 514 passed、3 skipped。
