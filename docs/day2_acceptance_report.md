# Day 2 Acceptance Report

## 环境与配置

验收日期：2026-07-22（Asia/Shanghai）。

真实链路使用项目 `.env` 中已配置的服务，但报告不记录 API Key：

| 项目 | 值 |
|---|---|
| Embedding model | `qwen3.7-text-embedding` |
| Embedding dimension | 1024 |
| LLM model | `deepseek-v4-flash` |
| Chunk size | 350 characters |
| Chunk overlap | 40 characters |
| Dense top_k | 3 |

验收脚本为两组实验创建临时、隔离的 Chroma collection，运行结束后自动
清理，不修改项目默认 collection。两组使用相同文档、Embedding 模型、问题
和 `top_k`，唯一变量是 Chunk 策略。

## 内置文档清单

| 文档 | 类型 | 页数/结构 | 主要内容 |
|---|---|---|---|
| `langgraph_checkpoint.md` | Markdown | H1/H2 | checkpointer、`thread_id`、配置步骤 |
| `embedding_batching.md` | Markdown | H1/H2/H3 | `embed_documents`、批处理、异常与配置项 |
| `context_citation_guide.md` | Markdown | H1/H2/H3 | 上下文预算、去重、PDF/Markdown 引用 |
| `dense_retrieval_guide.pdf` | PDF | 2 pages | Dense Retrieval 与 Chroma 元数据 |
| `ingestion_recovery_manual.pdf` | PDF | 3 pages | 失败检测、跨页恢复令牌与验证流程 |

五份文档均为本项目自行编写的小型测试资料，随仓库许可证分发；没有复制
第三方正文、API Key 或隐私数据。PDF 为可提取文本的 born-digital PDF，
不依赖 OCR。详细说明见 `knowledge/README.md`。

## 测试问题

完整机器可读问题集位于 `knowledge/day2_questions.jsonl`。每个文档包含两个
问题：

| ID | 文档 | 问题摘要 | 预期位置 |
|---|---|---|---|
| d2-q01 | langgraph_checkpoint.md | 哪个运行时选项必须稳定 | Required conversation identifier |
| d2-q02 | langgraph_checkpoint.md | 持久部署使用哪类 checkpointer | 顶层说明 |
| d2-q03 | embedding_batching.md | 70 个文档、batch size 32 产生几批 | Document embedding |
| d2-q04 | embedding_batching.md | 向量维度错误对应哪个异常 | Failure contract |
| d2-q05 | context_citation_guide.md | 使用哪两个标识去重 | Duplicate evidence |
| d2-q06 | context_citation_guide.md | 无可用上下文时如何处理 | Missing evidence |
| d2-q07 | dense_retrieval_guide.pdf | distance 如何转换为 dense score | page 2 |
| d2-q08 | dense_retrieval_guide.pdf | 哪些元数据保证结果可追踪 | page 2 |
| d2-q09 | ingestion_recovery_manual.pdf | 失败后记录哪个恢复令牌 | page 2 |
| d2-q10 | ingestion_recovery_manual.pdf | 重用令牌及跨页完成验证 | pages 2-3 |

真实回答验收选用 d2-q01（Markdown）与 d2-q10（跨页 PDF）。

## Recursive 与 Optimized 的参数

| 实验 | Markdown | PDF | 其他参数 |
|---|---|---|---|
| Recursive | `recursive` | `recursive` | size=350, overlap=40, top_k=3 |
| Optimized | `markdown_heading` | `pdf_page_aware` | size=350, overlap=40, top_k=3 |

两组入库后的总 Chunk 数均为 32，因而对比没有通过增加优化组候选数量来
制造优势。

| 文档 | Recursive chunks | Optimized chunks |
|---|---:|---:|
| context_citation_guide.md | 8 | 8 |
| embedding_batching.md | 7 | 7 |
| langgraph_checkpoint.md | 3 | 3 |
| dense_retrieval_guide.pdf | 5 | 5 |
| ingestion_recovery_manual.pdf | 9 | 9 |

## 检索结果对比

### Markdown：d2-q01

问题：`Which runtime option must stay stable so LangGraph can recover the same conversation state?`

| 策略 | Rank | Section | Dense score | Chunk chars |
|---|---:|---|---:|---:|
| Recursive | 1 | 无结构元数据（顶层介绍） | 0.7100 | 260 |
| Recursive | 2 | 无结构元数据（包含 `thread_id` 答案） | 0.7042 | 301 |
| Recursive | 3 | 无结构元数据（配置总结） | 0.6047 | 253 |
| Optimized | 1 | Required conversation identifier | 0.6611 | 235 |
| Optimized | 2 | LangGraph Checkpoint Quick Guide | 0.6598 | 187 |
| Optimized | 3 | Configuration summary | 0.5991 | 213 |

Recursive 的答案段位于第 2；Markdown 结构切分后，精确答案章节位于第 1，
并带有可定位的章节路径。Top-3 构建后的上下文从 905 字符降为 844 字符。
不同文本粒度的绝对 Dense score 不应直接横向解释为质量提升，本报告使用
答案段排名、章节定位和上下文长度作为证据。

### PDF：d2-q10

问题：`After a failed batch, which token is reused and which verification proves recovery completed?`

| 策略 | Top-3 pages | Top-3 chunk chars | Context chars |
|---|---|---|---:|
| Recursive | 3, 2, 2 | 219, 215, 258 | 828 |
| PDFPageAware | 3, 2, 2 | 219, 215, 258 | 828 |

两种策略都正确召回 page 2 的 `INGEST_RETRY_TOKEN` 与 page 3 的验证条件。
排名和上下文长度实质相同。原因是 Day 1 `RecursiveChunker` 已经逐页处理，
而 `PDFPageAwareChunker` 的当前主要增益是显式策略语义和稳定页码保证，并未
实现跨页合并或额外版面恢复。

## 答案与来源对比

真实 LLM 调用成功，四个答案均非空。

### Markdown

- Recursive 回答正确指出 `thread_id`，引用 `[S2]`；来源文件正确，但
  `section` 与 `heading_path` 均为空。
- Optimized 回答正确指出 `thread_id`，引用 `[S1]`/`[S3]`；`[S1]` 明确
  定位到 `langgraph_checkpoint.md | section Required conversation identifier`。

### PDF

- Recursive 与 PDFPageAware 均回答 `INGEST_RETRY_TOKEN` 需要重用。
- 两者均引用 page 2 的令牌定义和 page 3 的完成验证。
- Optimized 的结构化来源示例：
  `ingestion_recovery_manual.pdf | page 3`、
  `ingestion_recovery_manual.pdf | page 2`。

## 优化有效案例

d2-q01 是本次明确的结构切分优势案例：在相同模型、query、top_k 和总 Chunk
数量下，答案所在章节从 Recursive 的 rank 2 提升到 Optimized 的 rank 1；
引用从“只能定位文件”提升到“文件 + Required conversation identifier 章节”；
同时 Top-3 上下文减少 61 字符，降低了无关标题和相邻章节噪声。

该结果来自真实 Embedding 检索，没有重排、手工改序或修改检索分数。

## 未达到预期的案例

PDFPageAware 在 d2-q10 上没有比 Recursive 获得更高排名或更短上下文。两者
输出相同页序列与长度。此结果符合当前实现：两个 Chunker 都严格按页拆分并
复用相同的页内递归算法。后续若需要 PDF 质量差异，应在评估驱动下考虑页眉
页脚清理、段落恢复或 parent-child retrieval，而不是虚构本阶段收益。

## pytest 结果

执行命令：

```bash
cd backend
uv run pytest -q
```

结果：

```text
158 passed in 18.10s
```

其中内置语料专项测试为 `4 passed`，覆盖恰好五份文档、全部可解析、两个
PDF 均不少于两页、每个文档两个问题，以及优化 Chunk 的章节/页码元数据。

## 可复现命令

生成三页 PDF（仅在需要重新生成 fixture 时）：

```bash
cd backend
uv run --with reportlab python scripts/generate_builtin_pdf.py
```

真实检索对比：

```bash
cd backend
uv run python scripts/day2_acceptance.py
```

真实检索 + DeepSeek 回答对比：

```bash
cd backend
uv run python scripts/day2_acceptance.py --with-answers
```

脚本不会打印 API Key，并使用临时 Chroma collection。PDF 生成脚本启用了
ReportLab `invariant` 模式；重复生成前后 SHA-256 均为
`E7BADCC022547BF7A5A2FA9824EF7F1D79100057F3374C7EB7DA98DAC87EA24B`。

## Day 2 验收结论

- [x] 五份小型、合规、可解析的内置技术文档。
- [x] 多级 Markdown、相似章节、专有名词/函数名/配置项覆盖。
- [x] 两页与三页数字文本 PDF，包含跨页问题。
- [x] 每份文档至少两个验收问题。
- [x] Recursive 与结构感知策略在隔离 collection 中公平对比。
- [x] Markdown 回答来源包含文件和章节。
- [x] PDF 回答来源包含文件和页码。
- [x] 一组真实、可复现的结构切分优势案例。
- [x] DeepSeek 返回非空答案且引用编号与结构化来源一致。
- [x] Day 1/Day 2 全量测试通过。

Day 2 验收通过。

## 已知问题与 Day 3 输入

1. PDFPageAware 当前与页级 Recursive 的检索表现相同，没有额外版面恢复能力。
2. Dense Retrieval 对专有配置项有效，但尚未加入 BM25、RRF 或 Rerank；这些
   不属于 Day 2 范围。
3. 当前问题只执行单轮 RAG；Router、Query Rewrite 和 LangGraph 编排留给
   Day 3。
4. 验收语料规模很小，本报告是功能与对比证据，不替代正式 Evaluation。
