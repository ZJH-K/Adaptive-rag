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

`D5-01`

## 任务名称

关闭 Day4 运行时装配与请求级诊断缺口

## 目标

在接入 Reranker 和 Langfuse 前，先关闭 Day4 Review 中会直接破坏 Day5 可信度的三个主要问题：

1. 持久化 Chroma 重启后，首次 Hybrid 查询即可使用恢复后的 BM25；
2. 检索诊断不再依赖共享可变 `last_diagnostics`；
3. Dense、BM25 和 Fusion 的候选数量由单一权威配置控制。

本任务不实现 Reranker 和 Langfuse，只建立稳定的运行时基础。

## 上下文

Day4 已具备 Tokenizer、BM25Index、BM25Retriever、RRF 和 HybridRetrievalPipeline，但审查发现：

- 测试通过手工重建 BM25，应用本身没有唯一启动恢复路径；
- Pipeline 实例字段 `last_diagnostics` 会被并发请求覆盖；
- Pipeline 只对 Retriever 已返回的结果切片，不能真正控制底层 Chroma/BM25 召回数。

Day5 的候选过召回、Rerank Trace 和后续 SSE 都依赖这些问题先被修复。

## 范围

### 必须完成

1. 建立单一、可测试的检索运行时装配入口：
   - 从持久化 Chroma 读取全部 Chunk；
   - 初始化或重建 BM25Index；
   - 构造 DenseRetriever、BM25Retriever、HybridRetrievalPipeline；
   - 保证新进程首次查询即可获得 BM25 结果。

2. 将检索诊断改为请求局部数据：
   - 不允许通过共享实例属性保存当前请求事实；
   - 推荐返回结构化结果，例如 `RetrievalResult(hits, diagnostics)`；
   - 若为兼容现有 `Retriever.retrieve(query) -> list[SearchHit]`，可提供新的内部接口并由 Agent/Service 适配；
   - 不得让 Agent 感知 Dense、BM25、RRF 的内部细节。

3. 统一 Top-N 配置：
   - 一个配置源控制 Dense 实际查询数量；
   - 一个配置源控制 BM25 实际查询数量；
   - Fusion 候选上限必须明确；
   - 不得出现“配置为 50、底层仍只取 20”的假生效情况。

4. 处理最小一致性问题：
   - BM25 重建应使用不可变快照或锁，避免查询看到半更新状态；
   - Chroma 已写入但 BM25 重建失败时，必须留下明确错误或可重建状态；
   - 不要求实现复杂事务或分布式锁。

5. 更新或新增配置、类型、工厂和测试。

### 可修改区域

- `backend/src/config.py`
- `backend/src/rag/retrieval/`
- `backend/src/rag/ingestion/`
- 新增稳定的 runtime/bootstrap/composition 模块
- 对应测试文件
- 必要的导出文件

### 不在范围

- Reranker 实现；
- Langfuse SDK 接入；
- FastAPI 生命周期；
- SSE；
- Streamlit；
- Docker；
- 完整 Evaluation；
- BM25 磁盘级独立持久化。

## 约束

1. 保持 `SearchHit` 为统一检索结果模型，不创建 DenseHit、BM25Hit 等平行公开模型。
2. Agent 仍只能依赖抽象 Retriever 契约。
3. 不得把请求级诊断放到模块全局变量、单例字段或线程不安全缓存。
4. 不得为了启动恢复而在每次查询全量重建 BM25。
5. 默认离线测试不得调用外部 API。
6. 不提前开发 Day6 API/UI。
7. 任何公共接口变化必须同步更新调用方和回归测试。

## 验证方式

至少新增以下自动化测试：

1. `持久化数据 -> 新运行时实例 -> 首次 Hybrid 查询`，断言 BM25 分支真实参与；
2. 两个并发或交错请求的 diagnostics 不互相覆盖；
3. Dense Top-N 配置真实传入 Chroma 查询；
4. BM25 Top-N 配置真实传入 BM25 查询；
5. Fusion 候选上限按配置生效；
6. BM25 重建失败时，不返回“成功完成入库”的假状态；
7. 既有 Day1-Day4 全量测试无回归。

建议执行：

```bash
uv run pytest -q
uv run pytest backend/tests/test_retrieval.py backend/tests/test_ingestion.py -q
```

若项目测试文件名不同，按实际结构执行等价测试。

## 最终交付

1. 完整代码修改；
2. 新增/更新测试；
3. 一份 `docs/day5_task01_runtime_hardening_report.md`，至少包含：
   - 修改文件；
   - 新的装配路径；
   - Top-N 配置流向；
   - diagnostics 数据流；
   - BM25 启动恢复证据；
   - 测试命令与结果；
   - 已知限制；
4. 在最终回复中列出：
   - Changed Files；
   - Implementation Summary；
   - Validation Results；
   - Remaining Risks。
