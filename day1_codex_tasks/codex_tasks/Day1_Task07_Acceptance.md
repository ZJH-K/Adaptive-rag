# Day 1 Task 07：完成端到端测试与 Day 1 验收

## 开始前必须阅读

### 项目设计文档

必须阅读：

```text
adaptive_rag_project_technical_spec.md
```

重点查看：

- 第 4.1 节文档入库链路；
- 第 11.1 节 Dense Retrieval；
- 第 19 节 Day 1 验收标准；
- 第 20 节每日停止条件；
- 第 21 节测试要求。

### 开发规则

必须阅读并遵守：

```text
AGENTS.md
```

### AnyKB 仓库

本任务不需要查看 AnyKB。

原因：当前任务只负责验证本项目已经实现的 Day 1 链路，不新增参考实现。

---

## 目标

对 Day 1 全链路进行统一收口，确保代码不仅模块测试通过，还能完成真实 Markdown/PDF 入库、持久化和三个问题的 Dense Retrieval。

---

## 上下文

Day 1 最终验收标准：

- 一个 Markdown 和一个 PDF 可以成功入库；
- PDF Chunk 保存页码；
- Markdown Chunk 保存来源；
- 重复入库不会无限产生重复 Chunk；
- Chroma 重启后数据存在；
- 三个测试问题可以返回相关 Chunk；
- pytest 全部通过。

本任务原则上不增加新的核心架构，只负责：

- 补充测试；
- 修复 Day 1 范围内缺陷；
- 增加 Smoke Test；
- 输出验收文档。

---

## 范围

完成以下内容：

1. 整理并补全 Day 1 全部测试。
2. 增加端到端集成测试：
   - Markdown Parse → Chunk → Embed → Chroma；
   - PDF Parse → Chunk → Embed → Chroma；
   - Query → Embed → Dense Retrieval。
3. 在 `knowledge/markdown/` 准备一个小型技术文档。
4. 在 `knowledge/pdf/` 准备一个至少两页文本的小型 PDF。
5. 创建：

```text
backend/scripts/day1_smoke_test.py
```

6. Smoke Test 完成：
   - 初始化配置；
   - 入库 Markdown；
   - 入库 PDF；
   - 输出 document_id 和 Chunk 数量；
   - 对相同文件再次入库；
   - 检查 Chroma 数量未异常增长；
   - 创建新的 `ChromaVectorStore` 实例；
   - 检查持久化数据仍存在；
   - 执行三个测试问题；
   - 打印每个问题的 Top-K 文本、来源、页码和 dense score。
7. 创建：

```text
DAY1_ACCEPTANCE.md
```

8. 在验收文档中记录：
   - 运行环境；
   - 自动化测试命令；
   - Smoke Test 命令；
   - 人工验收清单；
   - 实际结果；
   - 已知限制。
9. 修复测试过程中发现的 Day 1 范围内问题。

---

## 约束

1. 自动化 pytest 使用 Fake Embedding，不依赖网络。
2. `day1_smoke_test.py` 使用真实 Embedding 配置，用于开发者手工验收。
3. API Key 缺失时，Smoke Test 必须给出清晰提示。
4. Smoke Test 不启动 FastAPI 或 Streamlit。
5. 不允许为了通过测试而硬编码三个查询结果。
6. 三个查询必须经过真实 Query Embedding 和 Chroma 查询。
7. 测试文档应足够小，避免大量 API 调用和费用。
8. 不新增 Day 2 功能。
9. 不通过删除测试、降低断言质量或跳过测试完成验收。
10. 不记录或输出 API Key。
11. 不以本任务为由进行大规模重构。

---

## 验证方式

### 自动化验证

执行：

```bash
cd backend
uv run pytest -q
```

必须全部通过。

### 真实链路验证

配置 `.env` 后执行：

```bash
cd backend
uv run python scripts/day1_smoke_test.py
```

人工检查：

1. Markdown 入库成功；
2. PDF 入库成功；
3. PDF 检索结果显示正确页码；
4. Markdown 检索结果显示正确来源；
5. 重复入库前后 Chroma Chunk 总数不异常增长；
6. 重新初始化 Chroma Client 后仍能检索；
7. 三个问题都能返回内容相关的 Chunk；
8. 输出中不存在 API Key 等敏感信息。

测试问题根据实际测试文档编写，例如：

```text
文档中如何配置 LangGraph checkpoint？
状态持久化需要使用哪个标识符？
PDF 中提到的检索流程包含哪些步骤？
```

不得写死上述问题对应的检索结果。

---

## 最终交付

- 完整 Day 1 测试集
- Markdown 测试文档
- 两页以上 PDF 测试文档
- `backend/scripts/day1_smoke_test.py`
- `DAY1_ACCEPTANCE.md`
- 全量 pytest 结果
- 真实 Smoke Test 运行结果
- Day 1 验收总结，至少包含：
  - 已通过项目；
  - 未通过项目；
  - 已知限制；
  - 进入 Day 2 前需要处理的问题。
