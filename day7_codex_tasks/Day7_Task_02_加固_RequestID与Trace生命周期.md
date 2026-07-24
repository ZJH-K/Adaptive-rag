# Day 7 Task 02：加固 Request ID 与 Trace 生命周期

## 目标

修复客户端重复 `X-Request-ID` 导致 Trace 生命周期串线的问题，并消除 Observer 对已完成请求状态的无界内存保留。

完成后，服务端内部请求标识必须始终唯一；客户端请求 ID 只能作为相关性元数据。Trace 状态必须有明确的创建、完成、取消、失败和释放语义。

## 上下文

Day6 审查发现：

- 客户端提供的 `X-Request-ID` 被直接作为 `_statuses` 和 Langfuse 根 observation 的主键；
- 两个并发请求使用相同 Header 时，后一个请求可覆盖前一个请求状态；
- `SafeTraceObserver` 和 `NoOpTraceObserver` 永久保留所有完成请求，1000 个完成请求会留下 1000 条状态；
- `done.trace_id`、`trace_exported` 和 Langfuse parent 关系可能因此错配。

本项目允许客户端提供 correlation ID，但它不能成为内部生命周期唯一键。

## 范围

### 必须实现

1. 服务端为每次请求生成不可冲突的内部 `request_id`，建议使用 UUID/ULID。
2. 客户端 `X-Request-ID`：
   - 校验长度与可接受字符；
   - 保存为 `client_request_id` 或 correlation metadata；
   - 不得作为内部 `_statuses`、Langfuse root map 或资源生命周期的唯一键。
3. 明确并统一以下标识：
   - `request_id`：服务端内部唯一请求 ID；
   - `client_request_id`：可选客户端相关 ID；
   - `trace_id`：真实 Observer/Langfuse Trace ID；
   - `trace_exported`：是否确认导出；
   - `tracing_enabled/configured/available`：能力状态。
4. 重构 Observer 生命周期：
   - `start_request()` 返回请求级 handle 或状态；
   - `finish_request()` / `cancel_request()` / `fail_request()` 返回终态快照；
   - 返回终态后释放内部 active state；
   - API 发送 `done` 时使用该终态快照，不再依赖完成后从全局字典查询。
5. 对异常退出、客户端断连、Provider 异常均执行幂等清理。
6. 如果必须短期保留完成状态，只能使用有界 TTL/LRU，并给出明确容量与过期时间；优先只保留 active request。
7. Langfuse Adapter 使用内部唯一 `request_id` 维护 root observation。
8. No-op tracing 下同样不能积累完成请求状态。
9. 增加并发和容量测试。

### 建议顺带处理

- 避免在 async SSE 事件循环中同步执行耗时的全局 `flush()`；可改为线程执行、批量 flush 或 shutdown flush，但不能牺牲请求完成语义。
- 对“tracing enabled 但依赖缺失/配置无效”给出可诊断状态，而不是只返回看似有效的本地 trace ID。

### 不包含

- 不在本任务修改 Langfuse Dashboard 展示内容；
- 不接入新的追踪平台；
- 不实现分布式 Trace 存储；
- 不改变检索算法或 SSE 业务事件内容。

## 约束

1. 对外兼容优先：若已有客户端依赖 `X-Request-ID`，可以在响应 metadata 中回显 `client_request_id`，但内部 ID 必须独立。
2. 不得把 API Key、Headers 或完整 Prompt 写入 Trace metadata。
3. 清理逻辑必须幂等，重复 finish/cancel 不得抛出未处理异常或结束其他请求。
4. 真实 Langfuse 未配置时，不得把本地 correlation ID 宣称为已导出的 Langfuse trace ID。
5. 不得使用单例全局字典永久保存所有历史请求。

## 验证方式

### 必须覆盖的测试

1. 两个并发请求携带相同 `X-Request-ID`：
   - 内部 `request_id` 不同；
   - `trace_id` 不同；
   - root observation 不串线；
   - 每个请求 `done` 对应自己的 Trace。
2. 客户端不提供 Header：服务端仍生成唯一 ID。
3. 客户端提供超长或非法 Header：按既定策略拒绝或规范化，不影响内部唯一性。
4. 连续完成至少 1000 个 No-op 请求：
   - active state 数量回到 0；
   - 若使用有界 cache，数量不超过上限。
5. 正常完成、已知失败、未知失败、取消四种路径都释放状态。
6. 同一请求重复调用 finish/cancel：幂等且不影响其他请求。
7. tracing unavailable 时，`trace_exported=false`，并有明确 readiness 信息。

### 建议命令

```bash
cd backend
uv run pytest -q tests/test_observability_tracing.py tests/test_langfuse_adapter.py tests/test_api_chat_stream.py
uv run pytest -q
```

### 人工检查

- 查看 `/api/health` 或聊天 `done` 事件，确认各类 ID 语义清楚。
- 使用相同 `X-Request-ID` 并发发起两次请求，观察日志中内部 ID 不同。

## 最终交付

1. 服务端唯一 Request ID 生成与 client correlation 处理；
2. 有界、可释放、幂等的 Observer 生命周期；
3. 更新后的 Langfuse root 映射；
4. 并发重复 ID 测试；
5. 大量请求后的容量测试；
6. 更新的接口/字段说明；
7. 完成报告中明确每种 ID 的定义和状态释放策略。
