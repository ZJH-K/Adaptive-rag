# Day 7 Task 06：实现 A/B/C/D 实验 Runner 与报告

## 目标

实现可重复运行的 Evaluation Runner，使用同一数据集、同一知识语料和可审计配置自动执行 A/B/C/D 四组实验，输出逐样本 JSON 结果、聚合 JSON 和 Markdown 报告。

最终报告必须区分真实执行、失败、跳过和未配置状态，不能使用 Fake 排名或示例数字冒充正式指标。

## 上下文

技术文档规定四组实验：

| 实验 | Chunk | Retrieval | Rerank |
|---|---|---|---|
| A | Recursive | Dense | No |
| B | Optimized | Dense | No |
| C | Optimized | Dense + BM25 + RRF | No |
| D | Optimized | Dense + BM25 + RRF | Yes |

最终 README 应展示：

```text
Baseline → Chunk Optimization → Hybrid Retrieval → Rerank
```

Day4/Day5 的人工 fixture 只能证明管线行为，不能作为正式质量结论。Day6 还要求 Evaluation 与浏览器 Demo 使用同一权威工作流/检索实现。

## 范围

### 必须实现

1. 统一 CLI，例如：

```bash
uv run python evaluation/run_eval.py --experiment A
uv run python evaluation/run_eval.py --all
```

2. 为 A/B/C/D 定义显式、可序列化配置：
   - chunk strategy；
   - dense enabled；
   - BM25 enabled；
   - RRF 参数；
   - reranker enabled；
   - retrieve top N；
   - rerank top K；
   - model names；
   - collection/persist path；
   - dataset version。
3. 每个实验使用隔离的 Chroma collection 或隔离 persist 目录，避免不同 Chunk 策略/重复入库互相污染。
4. 以相同知识文件和相同问题集运行四组实验。
5. A/B/C/D 必须调用项目真实 Parser、Chunker、Embedding、Chroma、BM25、RRF、Reranker Adapter，而不是手工构造排名。
6. 检索评估至少记录：
   - retrieved chunk IDs；
   - relevant chunk IDs；
   - rank；
   - Hit Rate@K；
   - Recall@K；
   - MRR；
   - latency；
   - Dense/BM25/Fused/Rerank 分数（存在时）。
7. 答案评估至少记录：
   - generated answer；
   - expected keywords；
   - keyword coverage；
   - sources/citations；
   - generation latency。
8. 输出目录建议：

```text
evaluation/reports/<timestamp-or-version>/
├── config.json
├── samples_A.jsonl
├── samples_B.jsonl
├── samples_C.jsonl
├── samples_D.jsonl
├── summary.json
└── report.md
```

9. Markdown 报告包含：
   - 环境与配置；
   - 数据集版本和样本数；
   - 四组指标对比表；
   - 每阶段变化；
   - 失败/跳过项；
   - 至少 3 个成功案例和 3 个失败/退化案例；
   - 已知限制；
   - 运行命令。
10. 增加 `--validate-only` 或等价模式，在无外部凭据时验证数据集、配置和索引流程，但不得生成伪正式指标。
11. 外部能力处理：
   - Embedding 缺凭据：对应实验 `NOT RUN`，退出码和报告明确；
   - Reranker 缺凭据：D 标记 `SKIPPED/NOT RUN`，不能自动把 C 结果复制为 D；
   - Langfuse 非本任务必需，但若启用需记录 Trace 状态。
12. 支持重复运行：
   - 固定配置和语料时结果结构稳定；
   - 保存 run ID、时间、代码版本（可获取时）、Python 版本和依赖锁信息。
13. 增加 runner 单元/集成测试，外部调用使用 Fake Provider 只验证控制流；正式报告只能由真实执行生成。

### 结果诚信要求

- 不允许在运行后修改 dataset 标签以提高指标；
- 不允许只展示最好的一次运行而不保留失败记录；
- 不允许把 `SKIPPED` 写成 0 分后参与平均；
- 不允许把人工 fixture 结果合并进正式 summary；
- README 只能引用实际存在的 report 路径和结果。

### 不包含

- 不接入大规模在线 Benchmark；
- 不实现 RAGAS/LLM Judge 作为 P0；
- 不调优模型以追求绝对分数；
- 不修改核心检索算法，除非 runner 暴露出确定性 bug，若修改必须单独说明并补回归测试。

## 约束

1. Evaluation 与生产 Demo 必须复用同一 Retrieval/Workflow 核心，不得另写一套简化算法。
2. 每组实验的唯一差异必须来自实验配置，不能混入不同文档、不同问题或未记录参数。
3. 运行前必须清理或隔离索引，避免旧数据污染。
4. 真实 API 错误必须脱敏，报告不得包含密钥、Authorization 或完整请求头。
5. 对小数据集结论只能表述为“项目内对比”，不得外推为生产普适结论。
6. 若外部服务无法运行，交付代码和 `NOT RUN` 证据，不得伪造指标。

## 验证方式

### 自动化测试

1. 四组配置正确映射到对应 Chunk/Retrieval/Rerank 组合；
2. 每组使用隔离 collection/persist path；
3. 同一 dataset 被四组复用；
4. Sample result 可 JSON 序列化；
5. skipped 不参与聚合；
6. Provider 失败被记录为失败，不生成虚假 0 分；
7. 报告表格字段与 summary.json 一致；
8. 重复 run 不会叠加入库导致 Chunk 数增长；
9. `--validate-only` 无凭据可运行；
10. 使用 Fake Provider 的测试明确标记为 runner behavior test，不写入正式 reports。

### 真实验收命令

```bash
# 先校验
uv run python evaluation/run_eval.py --validate-only --all

# 有真实 Embedding/LLM/Reranker 配置时执行
uv run python evaluation/run_eval.py --all

# 复核后端回归
cd backend
uv run pytest -q
```

### 人工复核

- 随机抽查至少 5 条样本的 relevant Chunk 与文档证据；
- 检查 A→B→C→D 的变化是否能由配置解释；
- 检查报告是否同时展示退化/失败案例；
- 检查 D 在 Reranker 未配置时是否明确 NOT RUN。

## 最终交付

1. `evaluation/run_eval.py`；
2. A/B/C/D 实验配置；
3. 隔离索引和运行时装配；
4. 逐样本 JSONL、summary JSON、Markdown 报告生成器；
5. Runner 测试；
6. 至少一次 `--validate-only` 输出；
7. 有凭据时的真实报告；无凭据时的明确 `NOT RUN` 说明；
8. 完成报告，说明运行环境、真实执行状态、指标变化和限制。
