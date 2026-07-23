# D6-01：检索失败类型化与单路降级契约

## 目标

在接入 FastAPI 和 SSE 前，补齐 Dense、BM25、Chroma/Vector Store 的运行时失败边界，使 Hybrid Retrieval 在单路出现可恢复故障时能够继续使用另一条检索路径，并让双路失败或不可恢复错误以稳定、可脱敏的类型向上层传播。

完成后，SSE 层可以基于明确错误码产生 `error` / `done` 事件，而不是捕获任意异常或让连接无说明中断。

## 上下文

Day5 审查报告的 Major M3 指出：

- `_retrieve_path()` 目前只捕获 `EmbeddingRequestError`；
- BM25 测试使用了不符合真实语义的 `EmbeddingRequestError` 来模拟失败；
- BM25 抛出真实 `RuntimeError` 时会绕过降级并终止 Graph；
- Chroma/Vector Store 的可恢复运行故障和数据/编程错误没有统一边界。

当前实现的优点必须保留：

- Agent 只依赖统一 Retriever 协议；
- Dense、BM25、RRF、Rerank 细节不泄漏到 Agent；
- diagnostics 为请求局部数据；
- Reranker 的已知失败可以回退到 RRF 顺序；
- 未知编程错误应继续暴露，不能被静默吞掉。

## 范围

### 1. 建立最小、稳定的检索异常层次

在合适的稳定模块中定义类型化异常，至少能区分：

- Dense/Embedding 路径的可恢复运行故障；
- BM25 索引或分词路径的可恢复运行故障；
- Vector Store/Chroma 的可恢复服务故障；
- 双路均不可用时的总体检索失败；
- 数据契约错误、metadata 冲突、非法响应和编程错误等不可静默降级的问题。

异常应携带机器可判定的安全字段，例如：

```text
code
path
recoverable
safe_message
```

不要把 API Key、请求正文、完整 Provider 响应或堆栈写入对外字段。

### 2. 在适配器边界转换异常

- Dense Retriever / Embedding Client / Chroma Adapter 只把已知 Provider 或连接类故障转换为类型化异常；
- BM25 Retriever / Index 把索引不可用、陈旧且无法恢复、分词运行失败等转换为 BM25 路径异常；
- metadata 冲突、非法 SearchHit、越界索引和断言失败等继续传播为不可恢复错误；
- 禁止在 Pipeline 中通过宽泛 `except Exception` 把所有错误都降级。

### 3. 明确 Hybrid Pipeline 降级语义

至少实现并测试：

1. Dense 成功、BM25 可恢复失败：返回 Dense 结果；
2. BM25 成功、Dense/Embedding 可恢复失败：返回 BM25 结果；
3. 两路都无结果但无异常：返回空结果，不视为系统故障；
4. 两路均发生可恢复故障：抛出统一总体检索异常；
5. 任一路发生不可恢复的数据/编程错误：立即传播，不伪装为“单路降级”；
6. Reranker 失败仍按现有契约回退，不得被此次改动破坏。

### 4. 扩展请求级 diagnostics

在不引入共享可变状态的前提下，记录：

- 实际使用的检索模式；
- 哪些路径发生降级；
- 安全错误码；
- Dense/BM25 候选数；
- 是否进入 RRF、是否进入 Rerank；
- 最终结果数。

不要存储完整异常文本或敏感 Provider 内容。

### 5. 对接工作流失败状态

让 Agent/Workflow 能把总体检索失败映射为稳定的工作流失败状态或异常类型，为 D6-06 的 SSE 错误事件提供唯一输入。不要在本任务实现 FastAPI 或 SSE。

### 6. 补充测试

优先修改或新增：

- 真实 BM25 异常类型的单路降级测试；
- Chroma/Embedding 可恢复故障的单路降级测试；
- 双路失败测试；
- 空结果与失败的区分测试；
- 未知 `RuntimeError` / 数据契约错误不被吞掉的测试；
- Graph 级失败状态测试；
- diagnostics 脱敏和请求隔离回归测试。

## 约束

- 不实现 FastAPI、SSE、Streamlit 或 Day7 Evaluation。
- 不改变 `SearchHit` 为第二套检索结果模型。
- 不把 Dense/BM25 分支逻辑写入 Agent 节点。
- 不使用宽泛捕获将所有异常视为可恢复故障。
- 不改变 RRF 公式、排序稳定性、Top-N 下推或 ContextBuilder 来源映射。
- 不要求真实外部服务凭据；离线测试必须确定性运行。

## 验证方式

至少执行：

```bash
cd backend
uv run pytest -q tests/test_retrieval_pipeline.py
uv run pytest -q tests/test_workflow_failure_contract.py
uv run pytest -q
```

如果测试文件名与仓库实际名称不同，可使用等价专项命令，但必须在交付中列明。

人工检查：

1. 搜索新增代码，确认不存在吞掉未知异常的 `except Exception`；
2. 检查单路失败返回的结果仍保留 `dense_score` / `bm25_score` / `fused_score` / `rerank_score` 契约；
3. 检查 diagnostics 不含 API Key、Prompt 或原始响应；
4. 复现 Dense 成功 + BM25 故障，确认 Graph 仍可生成答案；
5. 复现双路故障，确认得到稳定错误码而不是裸 `RuntimeError`。

## 最终交付

Codex 最终答复必须包含：

1. 改动文件列表；
2. 新异常层次与可恢复/不可恢复判定说明；
3. 五类检索场景的实际行为表；
4. 新增或修改的测试列表；
5. 专项测试与全量测试的真实结果；
6. 剩余风险；
7. 新增 `docs/day6_task01_acceptance.md`，记录实现、命令、结果和未解决项。
