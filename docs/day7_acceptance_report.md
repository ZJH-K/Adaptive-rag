# Day 7 Final Acceptance Report

验收日期：2026-07-23（Asia/Shanghai）

## Changed Files

- `README.md`
- `NOTICE.md`
- `docs/architecture.md`
- `docs/assets/adaptive-rag-system-architecture.drawio`
- `docs/assets/adaptive-rag-system-architecture.png`
- `docs/assets/adaptive-rag-system-architecture.drawio.png`
- `docs/demo_script.md`
- `docs/demo_checklist.md`
- `docs/evidence/README.md`
- `docs/resume_description.md`
- `docs/interview_1min.md`
- `docs/interview_3min.md`
- `docs/interview_questions.md`
- `docs/day7_acceptance_report.md`

Task 08 未修改真实 `.env`、生产代码或正式 Evaluation 结果。

## Day 7 需求状态

| Task | 状态 | 核心证据 |
|---|---|---|
| 01 统一 LangGraph 与 SSE | PASS | 浏览器只使用 lifespan-owned compiled graph；`docs/day7_task01_acceptance.md` |
| 02 Request ID / Trace 生命周期 | PASS | 内部 ID 唯一、终态释放、LRU/TTL；`docs/day7_task02_acceptance.md` |
| 03 SSE 取消与资源释放 | PASS | 真实本地 TCP disconnect 集成测试；`docs/day7_task03_acceptance.md` |
| 04 正式 Evaluation 数据集 | PASS | 24 条、5 个来源、6 类问题、人工 evidence；`evaluation/DATASET.md` |
| 05 Evaluation 指标库 | PASS | Hit/Recall/MRR/关键词/延迟/Rerank Gain；`evaluation/METRICS.md` |
| 06 A/B/C/D Runner | PASS WITH GAP | A/B/C COMPLETED；D SKIPPED；正式 report 可复核 |
| 07 Docker / Compose | PASS | 双镜像、非 root、单 worker、上传持久化与重启恢复 |
| 08 最终文档与演示材料 | PASS WITH EVIDENCE TODO | 文档齐全；真实截图/视频/Trace 尚待人工采集 |

## Backend / Frontend Tests

本次实际执行：

```text
cd backend && uv run pytest -q
515 passed, 3 skipped, 1 warning in 109.96s

cd frontend && uv run pytest -q
20 passed in 8.84s
```

3 个 backend skip 是显式 opt-in 的外部 LLM structured、Reranker 和 Langfuse Smoke。
warning 是 Starlette `TestClient` 对当前 httpx 集成的上游弃用提示，不影响测试通过。

## Evaluation

本次执行：

```text
uv run --project backend python evaluation/run_eval.py --validate-only --all
```

结果：数据集版本 `day7-task04-v1`，24 条；A/B/C/D 均为 `VALIDATED`，原因
`validation_only_no_metrics`，验证阶段没有产生或伪造指标。

正式运行证据：

- `evaluation/reports/day7-task06-run/config.json`
- `evaluation/reports/day7-task06-run/summary.json`
- `evaluation/reports/day7-task06-run/report.md`
- `evaluation/reports/day7-task06-run/samples_A.jsonl`
- `evaluation/reports/day7-task06-run/samples_B.jsonl`
- `evaluation/reports/day7-task06-run/samples_C.jsonl`

正式状态：A/B/C `COMPLETED`（各 24/24，无 failed sample）；D `SKIPPED`，原因
`reranker_not_configured`。README 的全部指标直接抄录自同一 `summary.json`。当前
小样本没有证明 B/C 优于 A，不能宣称“显著提升”。

## Docker Verification

Task 07 实际完成：

- `docker compose config --quiet`；
- backend/frontend 镜像构建成功；
- 两个容器 UID 10001、health 为 healthy；
- 上传 1 个 Markdown 后得到 1 文档 / 3 Chunks；
- 重启 backend 后仍恢复 1 文档 / 3 Chunks，BM25 ready；
- 无 Provider 凭据时 `/api/live=alive`，严格 readiness 为 unavailable；
- `scripts/docker-smoke.ps1` 构建、启动、等待、重启、停止全流程通过；
- 停栈后没有残留 Compose 容器或网络。

证据说明见 `docs/day7_task07_acceptance.md`。

## External Provider Status

| 能力 | 状态 | 可声明范围 |
|---|---|---|
| Embedding | REAL RUN | 正式 A/B/C Evaluation 和 Task 07 上传使用真实配置 |
| LLM Generation | REAL RUN in Evaluation | A/B/C 正式答案生成完成；独立 structured Smoke 本次仍 skip |
| Reranker | NOT RUN | Adapter、离线契约和降级完成；D 无指标、无真实收益结论 |
| Langfuse | NOT RUN | SDK Adapter、离线生命周期/脱敏契约完成；无真实导出或 Dashboard 证据 |

配置文件中现在是否存在凭据，不会追溯改变正式报告当时的 Provider 状态。只有新运行并
保存脱敏证据后，才能更新 Reranker/Langfuse 状态。

## Screenshot / Video / Trace Evidence

| 交付物 | 状态 |
|---|---|
| 架构图 PNG + editable draw.io | AVAILABLE |
| Streamlit Demo screenshot/GIF | TODO — 不伪造 |
| 2–3 分钟视频 | TODO — Codex 仅提供脚本和检查清单 |
| Reranker real smoke evidence | NOT RUN |
| Langfuse Dashboard trace | NOT RUN |

命名、真实性和脱敏规则见 `docs/evidence/README.md`。

## Known Issues

1. 24 条小数据集规模有限，且当前 B/C 未优于 A；
2. D 组、真实 Rerank Gain 与 Langfuse Dashboard 尚无证据；
3. BM25/入库一致性仅支持单进程，Docker 固定单 worker；
4. 不支持 OCR、复杂表格/图片布局、认证、多租户和限流；
5. 当前仓库没有项目自身 LICENSE；AnyKB 源码复制前仍需核验上游许可证；
6. Starlette TestClient 有一条上游弃用 warning。

## Final Delivery Decision

**工程实现、可复现 Evaluation、Docker 与文档包达到代码交付标准；最终求职展示包为
READY WITH EVIDENCE GAPS。**

在公开声称完整 Demo 前，仍需人工按 `docs/demo_script.md` 录制 Streamlit 截图/视频。
真实 Reranker 与 Langfuse 只能在新 Smoke 成功、证据脱敏并提交后从 NOT RUN 更新。
