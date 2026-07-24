# Day 7 Task 03：验证异步 SSE 取消与客户端资源释放

## 目标

补齐生产实际使用的异步 Provider 流分支测试，并证明 HTTP 客户端在首个 token 后断开连接时，上游 Provider 流会被取消/关闭、后续事件停止发送、Trace 正确标记为 cancelled，外部 HTTP 客户端在应用 shutdown 时得到显式释放。

## 上下文

Day6 审查指出：

- 生产 `DeepSeekClient` 提供 `astream_generate()`，因此默认走异步流；
- 现有 Chat service Fake 主要覆盖同步 `stream_generate()` fallback；
- 现有取消测试只直接 `aclose()` service generator，不代表真实 ASGI/HTTP 断连；
- 共享 OpenAI-compatible Client 和 Embedding Client 没有完整纳入 lifespan close/aclose 契约。

这会造成“测试全部通过，但浏览器断开后 Provider 仍继续生成/计费”的风险。

## 范围

### 必须实现

1. 为生产异步流路径增加可注入、可测试的 async Provider Fake：
   - 实现 `astream_generate()`；
   - 能记录已产生 token、`aclose()`、取消异常和结束状态。
2. 增加真实 HTTP/ASGI 层断连集成测试：
   - 启动可控测试应用或本地 ASGI server；
   - 客户端读取第一个 `token` 事件后主动关闭连接；
   - 断言 Provider async iterator 被关闭；
   - 断言不会继续产生后续 token/sources/done；
   - 断言 Observer outcome 为 `cancelled`；
   - 断言请求级状态被释放。
3. 覆盖 `request.is_disconnected()`、Task cancellation 或等价断连传播路径。
4. 确保正常完成、Provider 报错、客户端取消三种路径都执行 `finally` 清理。
5. 为以下客户端增加明确生命周期接口：
   - DeepSeek/LLM sync client `close()`；
   - DeepSeek/LLM async client `aclose()`；
   - Embedding client `close()`；
   - 其他共享 Provider client（如实际存在）。
6. 在 FastAPI lifespan shutdown 中调用这些 close/aclose，并保证某个资源关闭失败时仍继续关闭其他资源。
7. 如果 Langfuse flush/shutdown 会阻塞事件循环，应采用安全的非阻塞调用方式或仅在 shutdown 集中执行。
8. 增加关闭幂等测试，重复 shutdown 不应失败。

### 测试实现建议

优先使用无外部网络依赖的确定性方案：

- 在随机本地端口启动 Uvicorn 测试进程/线程，应用注入 async Fake Provider；
- 使用 `httpx.AsyncClient.stream()` 读取首个 token 后关闭响应；
- 用 Event/Barrier 断言 Provider 收到取消，不依赖任意 `sleep`；
- 所有测试必须自动清理端口、进程、线程和临时目录。

若 ASGITransport 无法真实模拟 socket 断连，不得仅用它替代本任务的 HTTP disconnect 证据。

### 不包含

- 不调用真实 DeepSeek、Embedding、Reranker 或 Langfuse；
- 不做负载测试；
- 不新增 WebSocket；
- 不实现跨进程取消；
- 不改变正常 SSE 事件字段。

## 约束

1. 测试必须稳定、确定性、可在离线 CI 运行。
2. 不得通过长时间 `sleep` 猜测取消是否发生，应使用同步原语或明确状态。
3. 取消路径不应记录为普通成功；Trace outcome 必须可区分 `completed`、`failed`、`cancelled`。
4. 客户端断开后不得继续向已关闭响应写事件。
5. 清理代码不得吞掉原始业务异常；可以记录清理错误，但要保持主要异常语义。
6. 所有外部客户端关闭方法必须幂等。

## 验证方式

### 必须覆盖的测试

1. 生产 async branch 正常流：多个 Provider delta 原样进入多个 `token` 事件。
2. 首 token 后 HTTP 断连：Provider `aclose()` 被调用。
3. 断连后：无 sources/done 继续输出。
4. 断连后：Trace outcome 为 cancelled，Observer active state 清零。
5. Provider 在中途抛异常：输出安全 `error`，执行关闭和 Trace failure。
6. 正常结束：Provider、请求状态和必要资源均正确收尾。
7. 应用 lifespan shutdown：LLM sync/async client、Embedding client、Observer、Chroma 都被关闭。
8. 某个 close 抛异常：其他资源仍得到关闭。
9. 重复 shutdown：不报错、不重复破坏状态。

### 建议命令

```bash
cd backend
uv run pytest -q tests/test_api_chat_stream.py tests/test_chat_streaming_service.py tests/test_app_lifespan.py
uv run pytest -q
```

## 最终交付

1. 可测试的 async Provider 流适配；
2. HTTP 客户端断连集成测试；
3. Provider 取消/关闭证明；
4. Trace cancelled 与状态清理实现；
5. LLM、Embedding 等客户端的 close/aclose；
6. lifespan 资源释放与容错测试；
7. 完成报告，说明测试模拟方式、取消传播链和仍未覆盖的生产限制。
