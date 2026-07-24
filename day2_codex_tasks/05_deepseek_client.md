# 任务 05：实现 OpenAI-Compatible DeepSeek Client

> 项目：Adaptive RAG  
> 阶段：Day 2 — 基础问答与结构感知切分  
> 建议执行顺序：5 / 7  
> 前置任务：Day 1 的配置系统与 `.env.example`  
> 预计单次任务规模：中等，适合一次 Codex 会话

## 必须阅读

1. 项目技术文档：`adaptive_rag_project_technical_spec.md`
2. 当前仓库根目录的 `AGENTS.md`（如存在）
3. 与本任务直接相关的现有源码和测试
- AnyKB：无需读取；按 DeepSeek 的 OpenAI-compatible 接口和项目现有客户端风格实现。

> 不要为了“熟悉项目”无边界浏览整个 AnyKB 仓库。只有任务明确要求时，才阅读指定文件。

## 目标

实现一个最小、可测试、可替换的 DeepSeek Client，为 Day 2 基础 RAG 问答提供非流式生成能力，并为后续 Router、Query Rewrite 和 SSE 扩展保留清晰接口。

## 上下文

技术文档指定：

```env
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=...
LLM_MODEL=deepseek-chat
```

Day 2 只需要基础问答，不需要 LangGraph、Router、Rewrite 或 SSE。客户端应封装 OpenAI-compatible Chat Completions 调用，避免业务 Service 直接依赖具体 SDK 细节。

## 范围

### 必须实现

- 在合理位置新增 LLM Client，例如：
  - `backend/src/llm/client.py`
  - 或遵循当前仓库已有目录约定
- 从 Pydantic Settings 读取：
  - `LLM_BASE_URL`
  - `LLM_API_KEY`
  - `LLM_MODEL`
  - 可选 timeout、temperature
- 提供清晰的非流式生成接口，例如：
  - `generate(messages: list[...]) -> str`
  - 或等价异步接口
- 正确处理：
  - 未配置 API Key
  - 空响应
  - 网络超时
  - 上游非成功状态
- 将底层异常转换为项目级异常，保留可调试原因但不泄露 API Key。
- 支持依赖注入或传入 mock transport/client，便于测试。
- 更新 `.env.example` 和配置测试。
- 新增客户端单元测试，不调用真实 DeepSeek API。

### 不在范围内

- 不实现 Router。
- 不实现 Query Rewrite。
- 不实现 SSE/流式输出。
- 不接入 Langfuse。
- 不实现多模型路由、重试队列或复杂熔断。
- 不在本任务中实现完整 RAG Service。

## 约束

- 优先使用项目已有 OpenAI-compatible SDK；禁止同时引入第二套功能重叠 SDK。
- Client 层不拼接 RAG Prompt，不理解 `SearchHit`。
- API Key 不得出现在日志、异常消息、测试快照或 README。
- timeout 必须显式可配置或有合理默认值。
- 测试必须完全离线。
- 不将 DeepSeek 特有逻辑散落在业务层。
- 为 Day 3 结构化输出需求保留可扩展性，但不要提前实现复杂抽象。

## 验证方式

### 自动化测试

至少覆盖：

1. 正常响应提取 assistant 文本。
2. 缺少 API Key 时快速失败并给出明确配置错误。
3. 上游超时转换为项目级异常。
4. 上游空 choices / 空 content 被识别。
5. 自定义 base_url 和 model 被正确传递。
6. 日志和异常不包含 API Key。
7. 测试不访问外部网络。

建议命令：

```bash
uv run pytest backend/tests/test_llm_client.py backend/tests/test_config.py -q
```

### 手工检查

在配置真实环境变量后，允许执行一个最小 smoke test：

```text
用户：只回复“ok”
期望：返回非空文本
```

该 smoke test 不应成为 CI 必需条件。

## 最终交付

- DeepSeek/OpenAI-compatible Client 实现
- 配置项与 `.env.example` 更新
- 项目级异常定义（如需要）
- 离线单元测试
- 完成说明：
  - 公共接口
  - 错误映射
  - 测试命令与结果
  - 可选真实 API smoke test 结果
