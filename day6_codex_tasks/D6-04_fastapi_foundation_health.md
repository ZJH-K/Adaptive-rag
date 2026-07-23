# D6-04：FastAPI 应用基座、生命周期与健康检查

## 目标

建立 Day6 唯一的 FastAPI 应用装配入口，通过 lifespan 创建并复用 Retrieval/Agent Runtime，在关闭时正确释放 Chroma 与 Observability 资源；实现可诊断但不泄密的 `GET /api/health`。

## 上下文

技术规格要求：

```http
GET /api/health
```

基础响应需覆盖 `status`、`chroma`、`llm`、`embedding`。Day5 审查进一步要求：

- startup 唯一调用 `build_retrieval_runtime()`；
- shutdown 关闭 Chroma 并 flush/shutdown Langfuse；
- health 区分 enabled、configured、available；
- 本地 request ID 与真实 Langfuse trace ID 不得混淆；
- 基础安装若缺 observability extra，必须可诊断。

D6-01～D6-03 已提供失败契约、索引状态和观测状态，本任务负责将它们组合进应用层。

## 范围

### 1. FastAPI Application Factory

实现或完善：

```text
create_app(settings, runtime_factory=...)
```

要求：

- 测试可注入 Fake Runtime；
- 导入模块时不立即连接外部服务；
- 不在每个请求中重复创建 Chroma、BM25、Retriever、LLM Client 或 Observer；
- `app.state` 或类型化容器中只保存一套应用共享 runtime；
- 路由按 `api/routes/health.py`、后续 documents/chat 模块组织。

### 2. Lifespan

启动时：

1. 读取配置；
2. 构建 runtime；
3. 从持久化 Chroma 恢复 BM25；
4. 获取各组件 readiness；
5. 保存应用状态。

关闭时：

1. 停止接收新操作；
2. flush/shutdown observer；
3. 关闭 Chroma/runtime；
4. 对关闭异常进行记录但不阻塞整个退出流程。

### 3. 依赖注入

提供稳定依赖，例如：

- `get_runtime()`；
- `get_settings()`；
- `get_ingestion_service()`；
- `get_chat_service()`（可先为占位协议，后续 D6-06 实现）。

依赖缺失时返回明确服务不可用错误，不使用全局单例偷偷重建。

### 4. 健康检查模型

实现结构化响应，至少包含：

```json
{
  "status": "ok|degraded|unavailable",
  "chroma": {"status": "ready|unavailable", "chunk_count": 0},
  "bm25": {"status": "ready|degraded|rebuilding", "generation": 0, "chunk_count": 0},
  "llm": {"configured": true, "model": "..."},
  "embedding": {"configured": true, "model": "..."},
  "reranker": {"enabled": false, "configured": false, "available": false},
  "tracing": {"enabled": false, "configured": false, "available": false}
}
```

字段名可根据仓库现有契约微调，但必须表达同等语义。

健康检查默认不要每次调用真实 LLM/Reranker/Langfuse 外部请求；使用配置和本地 runtime 状态。真实探针作为显式 opt-in 或单独管理动作。

HTTP 状态约定：

- 核心服务可回答但可选能力降级：HTTP 200，`status=degraded`；
- Chroma/runtime 未初始化、核心依赖不可用：HTTP 503；
- 仅 Reranker/Langfuse 未配置不应让核心健康检查失败。

### 5. 通用 API 错误模型

建立最小错误响应：

```json
{
  "error": {
    "code": "...",
    "message": "...",
    "request_id": "..."
  }
}
```

- 安装 request ID middleware 或等价实现；
- 对已知应用错误做安全映射；
- 未知错误记录服务端日志，对客户端返回通用消息；
- 不暴露堆栈、文件路径、Prompt、API Key。

### 6. 测试

覆盖：

- app 导入不触发外部连接；
- lifespan 只构建一次 runtime；
- shutdown 调用 flush/close；
- 健康状态 ok/degraded/unavailable；
- 缺 Langfuse extra 时 health 明确显示 unavailable；
- BM25 `needs_rebuild` 时显示 degraded；
- request ID 出现在成功和错误响应；
- 核心 unavailable 返回 503；
- 测试环境不调用真实网络。

## 约束

- 不实现 documents/chat 业务端点；本任务只做 app、lifespan、health 和通用错误基座。
- 不实现认证、用户、CORS 泛化配置、多租户或后台管理。
- 不在 health 请求中执行昂贵的真实模型调用。
- 不把可选 Reranker/Langfuse 不可用等同于整个服务宕机。
- 不提前编写 Dockerfile 或 Docker Compose。

## 验证方式

至少执行：

```bash
cd backend
uv run pytest -q tests/test_api_health.py
uv run pytest -q tests/test_app_lifespan.py
uv run pytest -q
```

人工检查：

1. 启动应用后连续请求两次 `/api/health`，确认 runtime 没有重复构建；
2. 禁用 Reranker/Langfuse，确认 HTTP 200 且状态可解释；
3. 模拟 BM25 stale，确认 `status=degraded`；
4. 模拟核心 runtime 启动失败，确认 HTTP 503；
5. 关闭应用，确认 observer flush 与 Chroma close 被调用。

## 最终交付

Codex 最终答复必须包含：

1. 应用装配图或文字说明；
2. 改动文件列表；
3. health 响应字段和 HTTP 状态语义；
4. lifespan 启停顺序；
5. 新增测试与真实结果；
6. 尚未实现的 documents/chat 路由说明；
7. 新增 `docs/day6_task04_acceptance.md`。
