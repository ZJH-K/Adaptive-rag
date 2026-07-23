# D4-02：闭环 Router 与 Query Rewrite 结构化输出契约

## 任务定位

这是进入 Day 4 前的第二个阻塞修复。目标是把 Router/Rewrite 从“Prompt 要求 JSON + 事后 `json.loads`”提升为有明确调用契约、严格解析、可测试降级和可复现证据的结构化输出链路。

## 目标

1. 明确 Router 和 Query Rewrite 的结构化生成调用契约；
2. 在当前 LLM Client 能力范围内优先使用 provider/API 支持的 JSON 或结构化输出参数；
3. 保留严格 Pydantic 校验和安全降级；
4. 增加与真实 SDK/API 响应形状一致的集成测试；
5. 提供可选真实 DeepSeek Smoke Test，默认不依赖网络运行。

## 上下文

Day 3 审查指出：

- 当前节点调用通用 `generate()` 后直接 `json.loads`；
- 真实请求只发送 `model/messages/temperature`，调用协议没有保证 JSON；
- Fake LLM 只返回预设合法 JSON，无法证明真实 provider 响应形状和降级行为；
- 解析失败虽不会崩溃，但系统可能长期退化为“总是检索”或“不改写”而不易发现。

本任务不要求改变 Router 的业务规则，也不要求引入 Langfuse；只修复结构化输出契约和验证证据。

## 范围

### 必须完成

1. 检查当前 LLM Client 和所用 OpenAI-compatible SDK/API 的实际能力，不凭任务文档假设参数名；
2. 为 Router 和 Rewrite 提供明确的结构化生成入口，可选择：
   - 在通用 Client 中增加可选结构化输出能力；或
   - 增加专用 `generate_structured(...)` 方法；
   - 但不能在 Agent 节点中散落 provider 细节。
3. 若当前 provider/client 支持 JSON mode 或等价能力，则通过调用参数启用；若不支持，必须：
   - 使用严格、可复用的 JSON 提取器；
   - 处理 Markdown code fence、前后说明文字和空响应；
   - 最终仍由 Pydantic 模型严格校验；
   - 在交付说明中明确“协议保证”和“解析兜底”的边界。
4. Router 保留安全降级：解析或校验失败时保守进入检索，并保存非空原因；
5. Rewrite 保留安全降级：解析或校验失败时回退原问题；
6. 增加测试覆盖：
   - 合法 JSON；
   - fenced JSON；
   - JSON 前后存在说明文字；
   - 缺字段、错类型、额外非法结构；
   - 空响应；
   - provider 返回对象形状与当前 SDK 一致；
   - Router/Rewrite 的调用参数确实启用了已支持的结构化能力；
   - 不支持结构化能力时的兜底路径。
7. 增加一个显式 opt-in 的真实 Smoke Test 或脚本：
   - 无 API Key 时跳过；
   - 有 API Key 时调用最小 Router/Rewrite 样例；
   - 输出通过/失败和原始响应摘要，但不得泄漏密钥。
8. 如当前配置系统需要，增加清晰的结构化输出开关或能力配置，并更新 `.env.example` 注释。

### 允许修改

- `backend/src/llm/client.py`；
- `backend/src/agent/nodes.py`；
- `backend/src/agent/state.py` 中 Router/Rewrite 响应模型；
- 必要的 LLM 协议/工具模块；
- 配置和 `.env.example`；
- 对应测试、可选 smoke 脚本或测试标记。

### 不在范围内

- 改写 Router 业务 Prompt；
- Langfuse 或解析失败率监控平台；
- 外部服务统一重试框架；
- BM25、RRF、Hybrid Retrieval；
- FastAPI/SSE；
- 多 provider 抽象重构。

## 约束

1. 不得在单元测试中调用真实网络；
2. 真实 Smoke Test 默认跳过，必须通过环境变量或 pytest marker 显式启用；
3. 不得把 provider 专用字段散落到 `agent/nodes.py`；
4. 不得删除现有保守降级；
5. 不得仅通过更强 Prompt 宣称“结构化输出已稳定”；
6. 若 provider 无法提供协议级 JSON 保证，必须在交付说明中诚实标注，只能做到“调用能力 + 严格解析 + 可观察降级”；
7. 不提前接入 Langfuse。

## 验证方式

### 自动化验证

```bash
uv run pytest -q
```

并单独运行 LLM、Router、Rewrite 相关测试，例如：

```bash
uv run pytest -q backend/tests/test_llm_client.py backend/tests/test_agent_nodes.py backend/tests/test_agent_graph.py
```

### 可选真实 Smoke Test

提供明确命令，例如：

```bash
RUN_LLM_SMOKE=1 uv run pytest -q -m external_llm
```

或仓库风格一致的脚本命令。Smoke Test 至少覆盖：

- 一个无需检索问题；
- 一个需要检索问题；
- 一个带指代的 Rewrite 问题；
- 响应能通过模型校验；
- 失败时输出可诊断信息，不泄漏 API Key。

### 验收判定

- 仅 Fake LLM 返回预设 JSON，不算闭环；
- 必须能证明请求参数、响应形状、解析器和 Pydantic 校验共同工作；
- 所有失败路径必须有确定性降级测试。

## 最终交付

1. 完成结构化输出调用契约；
2. 完成严格 JSON 提取和 Pydantic 校验；
3. 完成 Router/Rewrite 降级测试；
4. 提供可选真实 Smoke Test；
5. 提供改动文件清单；
6. 提供全量及专项测试结果；
7. 明确说明 provider 是否真正支持协议级结构化输出；
8. 记录无法验证的外部服务限制；
9. 不提交 BM25/RRF 代码。
