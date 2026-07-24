# A/B/C/D Evaluation Runner

`run_eval.py` 使用正式数据集和生产 RAG 组件执行项目内对比。它不会读取 Day4/Day5 fixture，也不会用问题检索结果反向修改标签。

## 实验矩阵

| 组 | Chunk | Retrieval | Rerank |
|---|---|---|---|
| A | recursive | Dense | 关闭 |
| B | Markdown heading / PDF page-aware | Dense | 关闭 |
| C | Markdown heading / PDF page-aware | Dense + BM25 + RRF | 关闭 |
| D | Markdown heading / PDF page-aware | Dense + BM25 + RRF | 开启 |

A/B/C 的最终返回上限等于 `retrieve_top_n`，以便计算 Hit/Recall@10；D 使用配置的 `rerank_top_k`。每组拥有独立 persist 目录和 collection。Runner 拒绝写入非空输出目录或复用非空索引目录，不会把历史 Chunk 叠加到新实验。

## 命令

从仓库根目录执行：

```bash
# 不调用外部服务；校验数据集、证据 ID、四组配置和索引计划
uv run --project backend python evaluation/run_eval.py --validate-only --all

# 单组正式执行
uv run --project backend python evaluation/run_eval.py --experiment A

# 四组正式执行
uv run --project backend python evaluation/run_eval.py --all
```

可用 `--dataset` 指定数据集，用 `--output-dir` 指定一个不存在或为空的目录。默认输出到带 UTC 时间戳的 `evaluation/reports/` 子目录。

## 输出与状态

每次运行写入：

- `config.json`：数据集/知识文件哈希、Python/代码/依赖锁版本、Provider 配置状态及完整实验配置；
- `samples_<组>.jsonl`：仅为真实执行过的组生成，包含排名、各阶段分数、指标、答案、来源和耗时；
- `summary.json`：四组状态与聚合指标；
- `report.md`：直接由同一个 summary 对象生成的对比表和案例说明；
- `indexes/<组>/`：正式执行时的隔离 Chroma 数据。

状态含义：

- `VALIDATED`：只完成本地校验，不包含正式指标；
- `COMPLETED`：该组真实执行完成；
- `FAILED`：Provider、索引或样本失败；可能保留已完成样本，但状态不能作为完整组结论；
- `SKIPPED`：依赖组专属能力未配置，例如 D 缺少 Reranker；
- `NOT_RUN`：Embedding 或 LLM 等全组必需能力未配置。

`SKIPPED`、`NOT_RUN` 不生成 0 分，也不会复制其他组结果。生产 Retrieval Pipeline 出现 Dense/BM25/Reranker 降级时，Runner 将样本标记失败，避免改变实验定义后仍报告为完成。

## 可复现与安全

正式样本使用 `dataset.source` 对应的同一组 5 份知识文件。相关 ID 根据实验 Chunk 策略从 `relevant_chunk_ids_by_strategy` 选择。配置只记录模型名和凭据是否存在，不保存 API key、Authorization、Provider 响应体或完整异常消息。

已提交的 [validation report](reports/day7-task06-validation/report.md) 是无外部调用的校验证据，其中全部指标为 `N/A`，不得作为质量结论。

