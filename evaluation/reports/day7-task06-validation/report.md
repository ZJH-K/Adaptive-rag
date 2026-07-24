# Adaptive RAG Evaluation — eval-20260722T203727Z

## 环境与配置

- 模式：VALIDATE ONLY（不产生指标）
- 数据集版本：`day7-task04-v1`
- 样本数：24
- Python：`3.13.13`
- 代码版本：`b96efd74f4446add04a44a9968b8ee33a20d1d8c`
- 工作树状态：`dirty`
- Dataset SHA-256：`918772e23d2106d310df524d52c1a7bfc0964ffa328be53b0b9612fc1b3816a0`
- K：1, 3, 5, 10
- Embedding 模型：`qwen3.7-text-embedding`
- LLM 模型：`deepseek-v4-flash`
- Reranker 模型：`BAAI/bge-reranker-v2-m3`

| 组 | Chunk | Retrieval | Rerank | Collection |
|---|---|---|---|---|
| A | recursive | Dense | No | `adaptive_rag_eval_a` |
| B | source_optimized | Dense | No | `adaptive_rag_eval_b` |
| C | source_optimized | Dense + BM25 + RRF | No | `adaptive_rag_eval_c` |
| D | source_optimized | Dense + BM25 + RRF | Yes | `adaptive_rag_eval_d` |

## 四组指标对比

| 组 | 状态 | Hit@1 | Hit@5 | Recall@5 | MRR | 关键词覆盖率 | 检索延迟 ms |
|---|---|---:|---:|---:|---:|---:|---:|
| A | VALIDATED | N/A | N/A | N/A | N/A | N/A | N/A |
| B | VALIDATED | N/A | N/A | N/A | N/A | N/A | N/A |
| C | VALIDATED | N/A | N/A | N/A | N/A | N/A | N/A |
| D | VALIDATED | N/A | N/A | N/A | N/A | N/A | N/A |

## 阶段变化

- A→B（结构化切分）：MRR 变化 N/A。
- B→C（Hybrid + RRF）：MRR 变化 N/A。
- C→D（Rerank）：MRR 变化 N/A。

## 失败、跳过与未配置

- A: VALIDATED — `validation_only_no_metrics`
- B: VALIDATED — `validation_only_no_metrics`
- C: VALIDATED — `validation_only_no_metrics`
- D: VALIDATED — `validation_only_no_metrics`

## 成功案例

- 未产生可审计的真实改善案例。

## 失败或退化案例

- 未产生可审计的真实失败/退化案例。

## 已知限制

- 这是 24 条项目内小数据集对比，不能外推为生产环境普适结论。
- 外部 Provider 未配置或失败时不生成零分，也不复制其他组结果。
- 关键词覆盖率只能检查核心词出现，不能替代答案忠实度人工复核。

## 运行命令

```bash
uv run --project backend python evaluation/run_eval.py --validate-only --all
uv run --project backend python evaluation/run_eval.py --all
```
