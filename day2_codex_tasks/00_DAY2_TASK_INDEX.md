# Adaptive RAG — Day 2 Codex 单次任务包

本任务包依据项目技术文档中 **Day 2：基础问答与结构感知切分** 拆分。

> 原始需求后半句写了“拆分 Day 1”，但开头明确表示“现在开始做 Day 2”，且项目上下文中 Day 1 已经完成拆分，因此本包按 Day 2 执行。

## Day 2 总目标

完成：

```text
Dense Retrieval
→ Context Builder
→ DeepSeek
→ Answer + Sources
```

同时新增：

```text
MarkdownHeadingChunker
PDFPageAwareChunker
Chunker Factory
```

## 建议执行顺序

| 顺序 | 文件 | 任务 | 主要依赖 |
|---:|---|---|---|
| 1 | `01_markdown_heading_chunker.md` | Markdown 结构感知切分 | Day 1 Schema/Recursive |
| 2 | `02_pdf_page_aware_chunker.md` | PDF 页码感知切分 | Day 1 PDF Parser |
| 3 | `03_chunker_factory_and_ingestion_integration.md` | 工厂与入库接入 | 任务 1、2 |
| 4 | `04_context_builder_and_citations.md` | 上下文与引用 | Day 1 SearchHit |
| 5 | `05_deepseek_client.md` | DeepSeek Client | Day 1 配置 |
| 6 | `06_basic_rag_service.md` | 基础 RAG 问答服务 | 任务 3、4、5 |
| 7 | `07_builtin_docs_and_day2_acceptance.md` | 内置文档与最终验收 | 任务 1–6 |

## 并行建议

可并行：

- 任务 01 与任务 02
- 任务 04 与任务 05

必须串行：

- 任务 03 应等待任务 01、02
- 任务 06 应等待任务 03、04、05
- 任务 07 最后执行

## 给 Codex 的使用方式

每次只发送一个任务文档，并要求 Codex：

1. 先阅读仓库根目录 `AGENTS.md`。
2. 阅读任务中列出的必要文件。
3. 严格限制在“范围”内。
4. 执行“验证方式”中的测试。
5. 按“最终交付”返回改动摘要和测试结果。
6. 不要自行开始下一个任务。

## AnyKB 阅读原则

Day 2 的核心实现以本项目自行设计为主。本任务包没有要求 Codex 无边界阅读 AnyKB 仓库：

- MarkdownHeadingChunker：自行实现；
- PDFPageAwareChunker：技术文档明确要求重写；
- ContextBuilder、DeepSeek Client、RAG Service：本项目内部实现；
- 不迁移 AnyKB Agent Tool Loop。

## Day 2 总验收标准

- 同一个问题可使用 Recursive 和结构感知策略进行对比；
- 回答包含来源文件；
- PDF 引用包含页码；
- Markdown 引用包含章节；
- 至少记录一组结构感知切分优于 Recursive 的可复现案例；
- Day 1 既有测试无回归；
- Day 2 新增测试全部通过。
