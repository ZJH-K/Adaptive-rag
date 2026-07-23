# Day 7 Task 07：完成 Docker 镜像与 Compose 部署

## 目标

为 backend 和 frontend 提供可复现的 Docker 镜像与 Docker Compose 启动方式，使新用户按照 README 使用 `docker compose up --build` 可以启动项目并完成健康检查。

容器化必须忠实反映当前运行限制：Python 3.11、单 Uvicorn worker、本地 Chroma/BM25 单进程一致性、Langfuse Cloud 可选。

## 上下文

技术文档要求：

- Docker Compose 最低保证 frontend、backend 可启动；
- `data/` 和 `knowledge/` 挂载；
- frontend 通过 `BACKEND_URL=http://backend:8000` 访问后端；
- Langfuse 自部署属于 P2，一周 MVP 可优先 Langfuse Cloud。

Day6 审查补充：

- BM25 一致性锁只适用于单进程，Compose 先固定单 worker；
- 若镜像启用 Langfuse，必须安装 observability extra；
- Reranker/Langfuse 无凭据时 readiness 应显示 degraded/unavailable，而不是静默假成功；
- 共享 LLM/Embedding client 应纳入 lifespan 关闭。

## 范围

### Backend Dockerfile

1. 基于 Python 3.11 的稳定 slim 镜像；
2. 使用项目现有 `uv.lock`/`pyproject.toml` 安装锁定依赖；
3. 安装运行所需 extras：
   - frontend/backend 分开；
   - backend 如支持 Langfuse，明确安装 `observability` extra；
4. 使用非 root 用户运行；
5. 设置合理工作目录、缓存和字节码环境变量；
6. 暴露 8000；
7. 启动命令固定单 worker；
8. 不在镜像中写入 `.env`、API Key 或本地数据；
9. 添加 healthcheck 或由 Compose 配置 healthcheck。

### Frontend Dockerfile

1. 使用与项目兼容的 Python 版本；
2. 安装 frontend 锁定依赖；
3. 暴露 8501；
4. 通过环境变量读取 backend URL；
5. 不包含 Provider 密钥；
6. 非 root 运行。

### Docker Compose

1. 服务：至少 `backend`、`frontend`；
2. 端口：8000、8501；
3. 挂载：
   - `./data:/app/data`；
   - `./knowledge:/app/knowledge`；
4. `frontend` 等待 `backend` healthy；
5. backend 使用根目录 `.env` 或 `env_file`，但仓库只提交 `.env.example`；
6. 单 worker 明确写入命令或配置；
7. restart 策略适合本地 Demo；
8. 不默认启动 Langfuse 自部署数据库栈；
9. 如提供可选 profile，必须文档化且默认不增加复杂依赖；
10. 容器关闭时正确触发 lifespan shutdown。

### 配套内容

1. `.dockerignore`：排除 `.git`、缓存、测试产物、`.env`、本地 Chroma 数据、报告大文件等；
2. `.env.example` 补齐 Docker 必需变量和注释；
3. Docker smoke 脚本或 Make/Task 命令：
   - build；
   - start；
   - wait health；
   - 检查 frontend HTTP；
   - stop；
4. 可选：为 CI 增加 `docker compose config` 校验。

### 不包含

- 不部署 Kubernetes；
- 不实现多 worker；
- 不自建 Langfuse 完整数据库栈作为 P0；
- 不引入 Redis、Postgres 或消息队列；
- 不把真实密钥写进镜像或 Compose。

## 约束

1. 必须使用 Python 3.11，不得依赖开发机当前 Python 3.13 行为。
2. Backend 必须单 worker；README 明确原因：BM25 内存索引和入库锁当前仅保证单进程一致性。
3. Build 必须可重复，优先使用 lockfile；不得 `pip install` 无版本漂移依赖。
4. 容器中 `data/` 可写、`knowledge/` 可读。
5. 无外部凭据时，容器应能启动并通过基础 health；外部能力显示 configured/available 状态，不应启动即崩溃。
6. 不得为了 healthcheck 调用付费模型接口。
7. Compose 中不得出现真实 API Key。

## 验证方式

### 静态验证

```bash
docker compose config
```

### 构建与启动

```bash
docker compose build --no-cache
docker compose up -d
```

### 运行验证

1. `curl http://localhost:8000/api/health` 返回可解析 JSON；
2. health 明确显示 Chroma、LLM、Embedding、Reranker、Tracing 状态；
3. `curl -I http://localhost:8501` 或浏览器可访问 Streamlit；
4. frontend 容器通过内部服务名访问 backend；
5. 上传测试文档后 `data/` 持久化；
6. `docker compose restart backend` 后 Chroma 数据存在，BM25 在首次查询前正确恢复；
7. `docker compose down` 正常停止，日志无未关闭 client 警告。

### 测试回归

```bash
cd backend && uv run pytest -q
cd ../frontend && uv run pytest -q
```

## 最终交付

1. Backend Dockerfile；
2. Frontend Dockerfile；
3. `docker-compose.yml`；
4. `.dockerignore`；
5. 更新的 `.env.example`；
6. Docker smoke 脚本或命令；
7. 容器启动、重启恢复和关闭验证记录；
8. 完成报告，明确单 worker、可选外部能力和未包含的部署范围。
