# Adaptive RAG · Day 5 Codex 任务

> 阶段：Day 5 — Rerank 与 Langfuse  
> 协作方式：Codex 负责编码与自测，人工负责 Review 与验收  
> 基线：Day 4 已完成 Hybrid Retrieval，但审查结论为 **PASS WITH ISSUES**

## 必读材料

开始编码前必须阅读：

1. `adaptive_rag_project_technical_spec.md`
2. `Day4_Review_Report.md`
3. 仓库根目录 `AGENTS.md`
4. 与本任务相关的现有实现和测试

若文档与当前代码不一致：

- 先以当前代码的公开契约和已有测试为事实基线；
- 不得静默改写公共接口；
- 在交付报告中记录差异、选择和理由；
- 涉及契约变更时，必须同步修改测试和调用方。

## 任务编号

`D5-04`

## 任务名称

定义工作流失败语义与可观察状态

## 目标

为 Router、Rewrite、Retrieval、Rerank 和 Generation 建立统一、可测试的失败契约，避免外部服务异常直接让 LangGraph 无说明中断，并为 Langfuse 和 Day6 SSE 提供稳定事件数据。

本任务不要求所有失败都“继续回答”，而是要求每个节点的行为明确、可观察、可测试。

## 上下文

Day3 Review 指出：

- Router/Rewrite 的网络错误不在解析降级范围内；
- Retriever/ContextBuilder 异常没有图级语义；
- Generation 异常会终止图；
- Day6 SSE 需要明确 error/done 行为。

Day4/Day5 又引入 Embedding、BM25、RRF 和 Reranker 降级。若没有统一契约，Langfuse Trace 会记录不完整，API 层也只能捕获通用异常。

## 范围

### 必须完成

1. 定义错误与降级模型，建议包含：
   - `stage`
   - `error_type`
   - `safe_message`
   - `degraded`
   - `fatal`
   - `fallback_used`
   - `timestamp` 或阶段耗时
   - 不含敏感信息的 provider/code

2. 扩展 AgentState 或统一运行结果，至少保存：
   - 当前阶段；
   - 降级事件列表；
   - 致命错误；
   - 是否有可返回答案；
   - 请求级 retrieval diagnostics；
   - 精确 context sources。

3. 明确各阶段语义：

   **Router**
   - 结构化解析失败：保守进入检索；
   - 网络/timeout：采用明确 fallback，并记录降级。

   **Rewrite**
   - 解析或调用失败：回退原问题，并记录降级。

   **Retrieval**
   - Dense 失败但 BM25 可用：单路降级；
   - BM25 失败但 Dense 可用：单路降级；
   - 两路均失败：不得伪造上下文。

   **Rerank**
   - 失败：保留 RRF/Dense 顺序。

   **Generation**
   - 失败：生成安全错误结果或明确致命状态；
   - 不得返回伪造的有依据答案。

4. 对聊天历史使用统一窗口策略：
   - Router、Rewrite、Direct Answer 使用一致的最大消息数/字符数约束；
   - 保留有限多轮能力；
   - 不实现长期记忆。

5. 补充节点级和图级异常测试。

### 可修改区域

- `backend/src/agent/state.py`
- `backend/src/agent/nodes.py`
- `backend/src/agent/graph.py`
- LLM/RAG 异常类型模块
- Retrieval Pipeline
- 测试文件

### 不在范围

- FastAPI/SSE 实现；
- 用户级错误文案最终设计；
- 自动重试队列；
- 熔断器；
- 多进程状态管理；
- Langfuse SDK 调用。

## 约束

1. 不暴露模型私有思维链。
2. 不把原始异常、请求头、API key 或完整文档内容写入公开状态。
3. fallback 必须确定性、可测试。
4. 不得把所有异常都吞掉并返回空字符串。
5. Direct 分支不得因为新增错误模型而触发检索。
6. 失败状态必须能被后续 Langfuse 和 SSE 直接消费，而不是重新解析日志文本。
7. 保持现有正常路径行为不变。

## 验证方式

至少覆盖：

1. Router timeout；
2. Router 非法 JSON；
3. Rewrite timeout；
4. Rewrite 非法 JSON；
5. Dense-only 失败；
6. BM25-only 失败；
7. Dense 与 BM25 均失败；
8. Reranker 失败；
9. ContextBuilder 失败；
10. Generation timeout；
11. 错误结果中不含 API key、完整 prompt、完整文档；
12. 降级事件顺序正确；
13. 有 fallback 的节点继续运行；
14. fatal 节点停止后续不安全步骤；
15. 长聊天历史被一致裁剪；
16. Direct Answer 可使用有限聊天历史；
17. 全量测试无回归。

## 最终交付

1. 错误/降级数据结构；
2. 更新后的 AgentState 与节点行为；
3. 图级异常测试；
4. `docs/day5_task04_failure_contract_report.md`，包含每个阶段的失败矩阵；
5. 最终回复说明哪些错误会降级、哪些会终止，以及对应状态字段。
