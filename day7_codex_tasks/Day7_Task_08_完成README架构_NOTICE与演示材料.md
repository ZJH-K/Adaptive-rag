# Day 7 Task 08：完成 README、架构、NOTICE 与演示材料

## 目标

把项目整理成可供新用户运行、可供面试官快速理解、可由用户录制 2–3 分钟 Demo 的最终展示包。

所有文档必须与实际代码、正式 Evaluation 报告和真实外部验证状态一致，不得把未运行的 Reranker/Langfuse Smoke 或人工 fixture 写成已证明的真实收益。

## 上下文

技术文档要求 README 至少展示：

1. 项目定位；
2. 为什么是 RAG 项目而非复杂 Agent；
3. 总体架构图；
4. AnyKB 复用边界；
5. Baseline 与优化 Pipeline；
6. Chunk 策略；
7. Hybrid Retrieval；
8. Rerank；
9. Evaluation 数据和结果；
10. Langfuse Trace 截图；
11. Streamlit Demo 截图；
12. 本地运行方式；
13. Docker 运行方式；
14. 已知限制；
15. 后续优化方向。

最终交付还包括 NOTICE、架构图、Demo、简历描述、一分钟和三分钟面试讲解。

Day6 审查要求 README 真实说明：

- 浏览器主链路实际是否经过 LangGraph；
- 单 worker 限制；
- 真实 Reranker/Langfuse 是否执行；
- Demo 证据是否可复放；
- 不能用手工 fixture 代替正式 Evaluation。

## 范围

### README

完成或重构根目录 `README.md`，至少包含：

1. 一句话项目定位和核心卖点；
2. Demo 截图/GIF/视频链接位置；
3. 技术栈；
4. 总体架构 Mermaid 图；
5. 实际生产请求链路，必须与 Task 01 完成后的代码一致；
6. 文档入库链路；
7. Router 与 Query Rewrite；
8. 三种 Chunk 策略；
9. Dense + BM25 + RRF；
10. Reranker 与失败降级；
11. Context/Sources 精确映射；
12. Langfuse/Observability 的 enabled/configured/available/exported 语义；
13. Evaluation 数据集、指标公式和 A/B/C/D 结果表；
14. 至少 3 个指标变化案例，必须引用正式 report；
15. 本地运行步骤；
16. Docker 运行步骤；
17. 配置说明；
18. 测试命令和最新真实测试结果；
19. AnyKB 复用与重写边界；
20. 已知限制；
21. 后续优化方向；
22. 项目目录；
23. 许可证/NOTICE 提示。

### 架构文档

1. README 内嵌 Mermaid 总体架构图；
2. `docs/architecture.md` 或等价文档，补充：
   - 入库流程；
   - 问答工作流；
   - Evaluation 运行流程；
   - Deployment 流程；
   - Request ID / Trace ID 生命周期；
3. 架构图不得继续展示已不存在的双 runner 或未实际启用的服务。

### NOTICE 与复用声明

1. 创建/完善 `NOTICE.md`；
2. 明确列出：
   - 参考仓库：`GU-Cryptography/anykb`；
   - 参考或适配区域；
   - 本项目重写区域；
   - 未复用区域；
3. 检查仓库中是否实际复制 AnyKB 源码；
4. 若无法从当前仓库确认 AnyKB LICENSE，必须写明 `LICENSE VERIFICATION REQUIRED`，不得猜测许可证；
5. 若已确认许可证，按其要求保留声明；
6. README 中的“复用”表述必须与 NOTICE 一致。

### Demo 与证据材料

Codex 负责准备，不要求 Codex 实际录屏：

1. `docs/demo_script.md`：2–3 分钟演示脚本；
2. `docs/demo_checklist.md`：录制前检查清单；
3. Demo 必须覆盖：
   - 上传 Markdown/PDF；
   - Router；
   - Rewrite；
   - Hybrid；
   - Rerank（仅真实可用时）；
   - 流式回答；
   - Sources 页码/章节；
   - Trace（仅真实导出时）；
   - Evaluation 报告；
4. `docs/evidence/README.md`：规定截图/日志/trace 证据文件命名和脱敏要求；
5. 不得创建“示例截图”冒充真实截图；没有真实证据时使用明确 TODO。

### 求职材料

1. `docs/resume_description.md`：
   - 一版 2–3 行简历描述；
   - 一版 4–5 行详细描述；
   - 只引用真实完成能力和正式指标。
2. `docs/interview_1min.md`；
3. `docs/interview_3min.md`；
4. `docs/interview_questions.md`，至少覆盖：
   - 为什么 Agent 只做 Router；
   - 为什么 Dense 不够；
   - 为什么 RRF；
   - 为什么先过召回再 Rerank；
   - Chunk A/B 如何公平比较；
   - Reranker/Langfuse 失败如何降级；
   - 单 worker 限制；
   - SSE 断连如何取消 Provider；
   - AnyKB 复用了什么、重写了什么。

### Day7 验收报告

创建 `docs/day7_acceptance_report.md`，包含：

1. Changed Files；
2. Day7 每项需求状态；
3. 后端/前端测试结果；
4. Evaluation 运行状态和 report 路径；
5. Docker 验证结果；
6. 外部 LLM/Reranker/Langfuse Smoke 状态；
7. 截图/视频/Trace 证据；
8. 已知问题；
9. 项目是否达到最终交付标准。

### 不包含

- 不由 Codex 伪造 Demo 视频、截图或 Dashboard Trace；
- 不在 README 写入真实密钥；
- 不新增大范围功能；
- 不把未来优化写成已完成；
- 不声称小样本 Evaluation 代表生产普适效果。

## 约束

1. README 中所有指标必须来自 Task 06 的正式 report，并可通过路径复核。
2. 外部 Reranker/Langfuse 未真实运行时，只能写“适配器和离线契约完成，真实 Smoke NOT RUN”。
3. 架构图必须反映实际代码路径，尤其是 LangGraph 与 SSE 的关系。
4. 测试数字必须来自本次实际命令输出，不得复制旧报告数字。
5. 所有命令须可复制，路径和环境变量名与仓库一致。
6. NOTICE 不得猜许可证。
7. 简历描述不能使用无法证明的“显著提升”“生产级”“高并发”等措辞。
8. 文档应以中文为主，可保留必要英文技术名词。

## 验证方式

### 文档一致性检查

1. README 的文件路径、命令、环境变量和端口真实存在；
2. Mermaid 能正常渲染；
3. README 中 Evaluation 数字与 `summary.json` 完全一致；
4. README 中测试结果与最新命令输出一致；
5. 架构图与生产代码实际调用路径一致；
6. NOTICE 与实际复用文件一致；
7. 未运行外部能力均明确标记；
8. Demo 脚本可在 2–3 分钟内完成；
9. 新用户仅按 README 可以完成本地或 Docker 启动。

### 建议命令

```bash
# 后端、前端最终测试
cd backend && uv run pytest -q
cd ../frontend && uv run pytest -q

# Evaluation 校验/执行
uv run python evaluation/run_eval.py --validate-only --all
# 有凭据时：uv run python evaluation/run_eval.py --all

# Docker

docker compose config
docker compose up --build -d
curl http://localhost:8000/api/health
curl -I http://localhost:8501
docker compose down
```

### 人工验收

- 按 README 从空环境执行一次；
- 按 Demo 脚本完整走一遍；
- 随机核对 README 中三个指标和三个引用；
- 检查所有截图、日志和 Trace 已脱敏。

## 最终交付

1. 完整 `README.md`；
2. `docs/architecture.md` 与 Mermaid 架构图；
3. `NOTICE.md`；
4. `docs/demo_script.md`；
5. `docs/demo_checklist.md`；
6. `docs/evidence/README.md`；
7. 简历描述、一分钟和三分钟面试讲解；
8. 面试问题清单；
9. `docs/day7_acceptance_report.md`；
10. 真实存在的 Evaluation、Docker、测试和外部 Smoke 证据引用；
11. 对尚未完成的截图、视频或外部 Trace 保留明确 TODO，不得伪造。
