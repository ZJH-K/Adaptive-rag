# Day 5 Integration Acceptance Report

## Overall Status

**PASS WITH EXTERNAL SMOKE GAPS**

Day5 的离线功能、完整本地集成、工程验收样本、请求隔离和全量回归均通过。真实 DeepSeek Router/Rewrite JSON mode Smoke 已成功；真实 Reranker 和 Langfuse Trace 因当前环境未配置对应凭据而未执行，因此不能给出无条件 PASS，也没有伪造外部执行证据。

## Summary

- Reranker 成功时能够改变 RRF 候选顺序，并保留 `dense_score`、`bm25_score`、`fused_score`、metadata；
- Reranker 公开故障会回退 RRF/Dense 顺序，不伪造 `rerank_score`，工作流仍可回答；
- 持久化 Chroma 经关闭和重新创建运行时后，BM25 在首次查询前自动恢复；
- Dense/BM25 Top-N 由同一 Settings 下推到底层 Retriever，候选池与最终 `rerank_top_k` 语义独立；
- Diagnostics 和 Trace 数据随当前请求结果返回，不依赖共享 `last_diagnostics`；
- Fake Langfuse 证明 Direct/RAG 拓扑、分数、耗时、降级和 fatal 状态完整且请求隔离；
- 6 条刻意构造的小样本使用真实 RRF 与 `RerankerAdapter`，5 条排名提升、1 条保持第 1；该结果仅是工程行为验收，不是统计质量结论；
- 当前配置的 `deepseek-v4-flash` 已通过真实 Router/Rewrite JSON mode 请求，未依赖审查报告指出的旧默认模型进行本次外部结论。

## Requirement Check

| Requirement | Status | Evidence |
|---|---|---|
| 全量离线测试 | PASS | `386 passed, 3 skipped` |
| Day5 专项测试 | PASS | 107 项通过；专项覆盖率 76%（按全 `src` 口径） |
| 全项目覆盖率 | PASS | 2033 statements，94% |
| 持久化 Chroma → 新运行时 | PASS | `test_day5_acceptance_integration.py` 真实关闭并重新打开 PersistentClient |
| BM25 首次查询前自动恢复 | PASS | 重启集成断言 index built、3 chunks、BM25 有命中 |
| Hybrid + Rerank + Context + Graph | PASS | 完整本地集成测试 |
| Fake Langfuse + 精确 sources | PASS | 8-stage Trace、`context_chunk_ids`、`S1` 和 source 对齐 |
| Rerank 正常路径 | PASS | Adapter、Pipeline、Graph 和小样本均覆盖 |
| Rerank 降级路径 | PASS | Provider failure 回退 candidate order，最终回答仍生成 |
| 请求级 diagnostics 无串线 | PASS | Barrier + 两线程交错 Graph 测试 |
| Top-N 真实下推 | PASS | Runtime/底层 Retriever/Pipeline 限制测试 |
| Direct/RAG Trace 拓扑 | PASS（Fake） | Direct 2 stages；RAG 8 stages |
| 真实 DeepSeek Router/Rewrite | PASS | 当前账号模型实际请求：1 passed |
| 真实 Reranker | NOT RUN | `RERANKER_API_KEY` 未配置 |
| 真实 Langfuse Trace | NOT RUN | Langfuse 未启用且凭据未配置 |
| Day6/Day7 范围控制 | PASS | 未增加 API、SSE、UI、Docker 或正式 Evaluation |

## Changed Files

- `backend/tests/test_day5_acceptance_integration.py`：完整的 restart-to-answer 离线集成证据。
- `backend/tests/fixtures/day5_rerank_cases.json`：6 条专有名词、函数名和干扰项小样本。
- `backend/scripts/compare_rrf_rerank.py`：使用生产 RRF 和 RerankerAdapter 的可复现脚本。
- `backend/tests/test_day5_rerank_sample.py`：固定小样本结果的回归测试。
- `backend/tests/test_reranker_smoke.py`：真实 Reranker opt-in Smoke。
- `backend/tests/test_langfuse_smoke.py`：缺少配置时明确 skip，而非误报失败或 PASS。
- `backend/pyproject.toml`：登记 `external_reranker` pytest marker。
- `.env.example`：明确外部模型必须按当前账号可用性确认，示例值均可覆盖。
- `backend/tests/test_llm_client.py`、`backend/tests/test_reranker.py`、`backend/tests/test_config.py`：离线协议测试使用测试模型名或只检查有效字符串，不再把某个 Provider 模型名作为产品正确性条件。

## Architecture Notes

完整验收链路：

```text
Persistent Chroma
  → process-style reopen
  → build_retrieval_runtime
  → BM25 restore
  → Dense + BM25
  → RRF
  → deterministic Reranker
  → ContextBuilder
  → LangGraph
  → FakeTraceObserver
  → grounded answer + exact context_sources
```

测试没有绕过运行时装配：首次 Chroma 客户端写入后被关闭，随后 `build_retrieval_runtime()` 从持久化语料重建 BM25。Graph 接收运行时唯一的 Hybrid Pipeline，最终断言 Rerank 后首个 Chunk、`context_chunk_ids[0]`、`context_sources[0].chunk_id`、`citation_id=S1` 和 Context 中 `[S1]` 完全一致。

Trace/diagnostics 数据来自当前 `RetrievalResult`，阶段快照不含正文，只含 Chunk ID 和四类分数。并发测试让两个 Graph 请求在 Dense 阶段通过 Barrier 真实交错，再按 trace ID 检查各自 8 条 observation，证明没有共享请求数据串线。

## Test Results

### Day5 专项测试

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q --cov=src --cov-report=term-missing `
  tests/test_reranker.py tests/test_retrieval_pipeline.py `
  tests/test_retrieval_runtime.py tests/test_langfuse_tracing.py `
  tests/test_workflow_failure_contract.py `
  tests/test_day5_acceptance_integration.py `
  tests/test_day5_rerank_sample.py tests/test_hybrid_agent_graph.py `
  tests/test_agent_graph.py tests/test_config.py
```

结果：`107 passed in 24.99s`。

### 全量离线回归

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
```

结果：`386 passed, 3 skipped in 45.34s`。

三个默认 skip：

1. 外部 LLM Smoke；
2. 外部 Langfuse Smoke；
3. 外部 Reranker Smoke。

## Coverage

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q --cov=src --cov-report=term-missing
```

结果：

```text
TOTAL  2033 statements  130 missed  94%
386 passed, 3 skipped in 64.18s
```

重点模块：

| Module | Coverage |
|---|---:|
| `agent/graph.py` | 97% |
| `agent/nodes.py` | 92% |
| `observability/tracing.py` | 93% |
| `retrieval/pipeline.py` | 96% |
| `retrieval/reranker.py` | 88% |
| `rag/runtime.py` | 90% |
| `context_builder.py` | 98% |
| `rag/service.py` | 100% |

专项测试单独按整个 `src` 统计为 76%；该数字包含 Day1–Day4 Parser、Chunker、Embedding 等不属于 Day5 专项命令的模块，不能解释为 Day5 核心模块只有 76%。

## Rerank Small-Sample Results

执行：

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\compare_rrf_rerank.py
```

结果：

| Case | RRF Rank | Rerank Rank | Change |
|---|---:|---:|---:|
| `thread_id` | 4 | 1 | +3 |
| `similarity_search` | 3 | 1 | +2 |
| `rrf_formula` | 4 | 1 | +3 |
| `reranker_model` | 4 | 1 | +3 |
| `langfuse_base_url` | 4 | 1 | +3 |
| `context_sources` | 1 | 1 | 0 |

描述性汇总：

```text
cases: 6
improved: 5
unchanged: 1
RRF MRR@5: 0.3889
Rerank MRR@5: 1.0000
RRF Hit@1: 1/6
Rerank Hit@1: 6/6
```

限制：Dense/BM25 排名与 Cross-Encoder 分数均为手工设计 fixture，脚本只证明生产 RRF、Adapter 和排序/字段传播按照预期工作。它不证明真实 BGE 模型在自然分布上的平均收益，也不应与 Day7 20–30 条正式 Evaluation 混用。

## Langfuse Trace Evidence

Fake Trace 的 RAG 拓扑：

```text
router
query_rewrite
dense_retrieval
bm25_retrieval
rrf_fusion
rerank
context_build
final_answer
```

本地完整集成断言：

- Trace ID 写入最终 Graph state；
- 8 个 observation 顺序与真实执行阶段一致；
- Dense/BM25/Fusion/Rerank 的 Chunk ID、四类分数、count 和 latency 来自当前请求 diagnostics；
- `context_build` 的 Chunk IDs 和 sources 与最终 Context 一致；
- `final_answer` 使用同一 trace ID；
- Fake Observer 记录请求已 finish；
- 不包含 API key、header、完整 prompt、Context 或候选正文。

这证明 Adapter 集成和待发送 payload 正确，但不能等价为“Langfuse Dashboard 已看到真实 Trace”。当前没有 Langfuse 凭据，真实 Dashboard 证据为 NOT RUN。

## External Smoke Results

### DeepSeek Router/Rewrite — PASS

安全配置检查：`LLM_API_KEY` 已配置，当前 `LLM_MODEL=deepseek-v4-flash`。未打印凭据。

命令：

```powershell
$env:RUN_LLM_SMOKE="1"
.\.venv\Scripts\python.exe -m pytest -q -s tests/test_llm_structured_smoke.py
```

结果：`1 passed in 18.45s`。

实际验证：

- 通用问题 Router 返回 `need_retrieval=false`；
- 上传文档问题 Router 返回 `need_retrieval=true`；
- Rewrite 返回独立的 LangGraph checkpoint 查询；
- 三次响应均通过 JSON mode 和严格 Pydantic 契约。

报告只保留不含凭据、请求头和私有文档的短 JSON 摘要。

### Reranker — NOT RUN

设置 `RUN_RERANKER_SMOKE=1` 后，测试明确显示：

```text
SKIPPED: RERANKER_API_KEY is not configured
```

没有 Provider 请求，没有真实 score，不宣称 PASS。

### Langfuse — NOT RUN

设置 `RUN_LANGFUSE_SMOKE=1` 后，测试明确显示：

```text
SKIPPED: Langfuse is not enabled or credentials are not configured
```

没有发送真实 observation，没有 trace_id 或 Dashboard 截图，不宣称 PASS。

## Known Issues

- 真实 Reranker 与 Langfuse 外部链路仍需凭据后验收；
- Langfuse observation 的业务阶段 latency 当前来自 Pipeline metadata，SDK observation 本身记录的是发送动作时间；
- 本次小样本是刻意构造的工程验收数据，不能替代 Day7 正式评估；
- BM25 重建与查询的并发一致性、Chroma 写入后 BM25 重建失败的一致性策略仍是 Day6 上传/查询并发前需要处理的问题；
- 本机验证环境是 Python 3.13.13；项目目标是 Python 3.11+，Day7 Docker 仍应固定并复测目标镜像版本。

## Day6 Readiness

**CONDITIONALLY READY**

可以进入 Day6 API/SSE 集成的基础：

- 唯一运行时装配和 BM25 启动恢复已验证；
- Top-N 配置、Hybrid、Rerank 和 fallback 已稳定；
- AgentState 已提供 `trace_id`、阶段、降级事件、fatal、answer availability、diagnostics 和精确 sources；
- Direct/RAG Trace 拓扑与并发请求隔离已验证；
- 全量 386 项离线测试和 94% statement coverage 通过。

进入 Day6 前/期间必须保留的门槛：

1. 配置 Reranker 凭据后执行真实 Smoke；
2. 配置 Langfuse 后生成至少一个真实脱敏 Trace，并保存 trace_id 或人工截图证据；
3. 在上传与查询并发前决定 BM25 rebuild 的锁/快照策略；
4. API shutdown hook 调用 Langfuse `flush()`/`shutdown()`；
5. SSE 直接消费已有结构化状态，不重新解析日志或重算 sources。
