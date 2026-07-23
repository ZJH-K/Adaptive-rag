# D6-07：Streamlit 前端与 Day6 端到端验收

## 目标

实现可演示的 Streamlit 页面，通过 FastAPI 完成 PDF/Markdown 上传、内置知识库加载、流式聊天、Sources 定位和 RAG 过程展示，并产出 Day6 端到端验收报告。

## 上下文

技术规格的 Streamlit 需求：

左侧栏：

- 知识库选择；
- PDF/Markdown 上传；
- Chunk 策略选择；
- 加载内置知识库；
- 文档数量和 Chunk 数量；
- 清空当前会话。

主区域：

- ChatGPT 风格聊天；
- 流式回答；
- Markdown 渲染；
- Sources 展示。

折叠过程面板：

```text
Router Decision
Query Rewrite
Dense Retrieval
BM25 Retrieval
RRF Fusion
Reranker Results
Langfuse Trace 状态
```

展示的是可观察工作流事件，不是模型私有思维链。

## 范围

### 1. 前端结构

推荐最小结构：

```text
frontend/
├── app.py
├── api_client.py
├── sse.py
└── tests/
```

可以根据仓库实际结构调整，但要把 HTTP/SSE 解析与页面渲染分开，避免所有代码堆进 `app.py`。

### 2. 后端配置

- 从环境变量读取 `BACKEND_URL`；
- 设置合理连接、读取超时；
- 对普通 JSON API 与 SSE 使用统一客户端封装；
- 不在前端保存 LLM、Embedding、Reranker 或 Langfuse API Key；
- 后端不可达时展示明确错误，不让 Streamlit 整页崩溃。

### 3. 左侧栏

实现：

- 单知识库选择（默认 `technical_docs`，不要扩展为多知识库管理）；
- 文件选择与上传按钮；
- 根据文件类型提供/校验 chunk strategy；
- 加载内置知识库按钮；
- 调用 stats 显示文档数、Chunk 数、BM25 状态；
- 清空会话按钮，只清理前端 session state。

上传完成后刷新统计，并提示完整成功、降级或失败；不能把 degraded 显示为普通成功。

### 4. 聊天区域

- 使用 `st.chat_message` / `st.chat_input` 或等价方式；
- 在 session state 保存当前浏览器会话消息；
- 发送最近有限窗口的 `chat_history`；
- 用户提交后立即显示用户消息；
- 解析 SSE `token` 并增量更新 assistant placeholder；
- 完成后把最终答案写入 session state；
- 支持 Markdown 渲染；
- 错误时保留已经收到的文本并展示安全错误。

### 5. Sources 展示

基于 SSE `sources` 事件：

- 按 `[S1]`、`[S2]` 顺序显示；
- PDF 显示文件名、页码、可选摘要；
- Markdown 显示文件名、章节/heading path；
- 不从 retrieval hits 自行推导 sources；
- 没有 sources 的 Direct Answer 不显示空面板。

### 6. RAG 过程折叠面板

消费 `route`、`rewrite`、`retrieval`、`done`：

- Router：是否检索 + 简短原因；
- Rewrite：独立检索问题；
- Dense/BM25：候选数与 degraded 状态；
- RRF：是否融合、最终候选；
- Reranker：enabled/configured/used/degraded、Top-K；
- Trace：request ID、tracing enabled、真实 trace ID、exported 状态。

不得显示：

- 完整 Prompt；
- chain-of-thought；
- API Key；
- Python stack trace；
- Langfuse 未导出时伪造可点击 ID。

### 7. SSE 客户端解析器

实现独立、可测试的增量解析：

- 支持网络分块在任意字符位置切开；
- 支持一个 chunk 中包含多个事件；
- 支持 UTF-8 中文跨 chunk；
- 忽略 keepalive/comment；
- JSON 错误产生可诊断前端错误；
- 页面 rerun/用户中止时关闭 HTTP stream。

不要通过一次性读取完整响应后再渲染。

### 8. Day6 端到端验收

至少完成以下真实链路：

1. 启动 backend 与 frontend；
2. `/api/health` 可用；
3. 上传一个 Markdown；
4. 上传一个可解析 PDF；
5. 加载内置知识库；
6. 上传后立即提问；
7. Direct 问题走 direct 分支；
8. 文档问题走 RAG 分支；
9. 模糊指代触发 Rewrite；
10. 回答 token 增量显示；
11. PDF source 定位页码；
12. Markdown source 定位章节；
13. Reranker/Langfuse 未配置时 UI 正确显示 unavailable/degraded；
14. 后端返回 error 时页面不崩溃；
15. 清空会话只影响当前 UI 状态。

### 9. 测试

自动化至少包括：

- SSE parser 分块边界、中文、多个事件、非法 JSON；
- API client 的 upload/load-default/stats；
- SSE direct/RAG/error/done 消费；
- session state 纯函数或状态转换测试；
- 使用 Fake Backend 的 Streamlit 调用契约测试；
- 后端全量回归。

不强制引入重型浏览器 E2E 框架；可以用 Streamlit AppTest（若当前版本支持）或可测试组件 + 手工 Smoke。必须诚实说明自动化覆盖边界。

## 约束

- UI 以可演示和清晰为目标，不追求高级视觉、动画或响应式设计。
- 不增加 React/Vue、用户登录、多租户、文件管理后台或会话持久化。
- 不在 Streamlit 进程中直接调用 RAG/LLM，所有业务通过 FastAPI。
- 不缓存或输出服务端 API Key。
- 不把 retrieval hits 当成最终 sources。
- 不提前实现 Day7 Docker、正式 Evaluation 和 README 全量包装。

## 验证方式

自动化示例：

```bash
cd frontend
uv run pytest -q

cd ../backend
uv run pytest -q
```

如果前端不使用独立 `pyproject.toml`，使用仓库实际命令并记录。

手工启动示例：

```bash
# 终端 1
cd backend
uv run uvicorn src.main:app --reload --port 8000

# 终端 2
cd frontend
uv run streamlit run app.py --server.port 8501
```

浏览器验收地址：

```text
http://localhost:8501
```

## 最终交付

Codex 最终答复必须包含：

1. 前端文件结构和职责；
2. Streamlit 与四个后端端点的调用关系；
3. SSE 增量解析与页面更新方式；
4. Sources 与过程面板字段说明；
5. 自动化测试真实结果；
6. 15 项端到端验收逐项结果，无法执行的外部项标 `NOT RUN`；
7. 至少两张本地截图建议清单：完整 RAG 回答、上传/过程面板；
8. 已知限制；
9. 新增 `docs/day6_acceptance_report.md`，作为 Day6 总验收报告；
10. 不得宣称未执行的真实 Reranker/Langfuse 验收已通过。
