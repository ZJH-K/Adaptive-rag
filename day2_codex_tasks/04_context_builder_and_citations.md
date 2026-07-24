# 任务 04：实现 ContextBuilder 与统一引用格式

> 项目：Adaptive RAG  
> 阶段：Day 2 — 基础问答与结构感知切分  
> 建议执行顺序：4 / 7  
> 前置任务：Day 1 的 `SearchHit`、Dense Retrieval；任务 01、02 提供的 page/section 元数据  
> 预计单次任务规模：中等，适合一次 Codex 会话

## 必须阅读

1. 项目技术文档：`adaptive_rag_project_technical_spec.md`
2. 当前仓库根目录的 `AGENTS.md`（如存在）
3. 与本任务直接相关的现有源码和测试
- AnyKB：无需读取；引用规范按本项目数据结构实现。

> 不要为了“熟悉项目”无边界浏览整个 AnyKB 仓库。只有任务明确要求时，才阅读指定文件。

## 目标

实现 `ContextBuilder`，将检索得到的 `SearchHit` 转换为受长度约束、顺序稳定、可被 LLM 使用的上下文，并生成统一来源信息。PDF 来源必须包含页码，Markdown 来源必须包含章节。

## 上下文

Dense Retrieval 已能返回相关 Chunk，但直接把原始结果拼进 Prompt 会带来重复、超长、元数据丢失和引用不可定位等问题。Day 2 的问答链路需要：

```text
list[SearchHit]
→ 去重与排序
→ 长度预算控制
→ 编号上下文块
→ 生成 sources
→ 提供给 DeepSeek 和最终答案
```

本任务不负责调用 LLM，只负责上下文与引用数据的构建。

## 范围

### 必须实现

- 新增或完善 `backend/src/rag/context_builder.py`。
- 定义清晰返回结构，可采用现有 Schema 或新增最小模型，例如：
  - `context: str`
  - `sources: list[...]`
  - `used_chunk_ids: list[str]`
- 保持输入检索顺序，除非有明确去重规则。
- 按 `chunk_id` 或 `content_hash` 去除重复结果。
- 提供可配置的上下文长度预算；可先使用字符数近似，但接口需清晰。
- 每个上下文块带稳定编号，例如 `[S1]`、`[S2]`。
- PDF 来源至少包含：
  - 文件名/来源
  - 页码
  - chunk_id
- Markdown 来源至少包含：
  - 文件名/来源
  - section 或 heading_path
  - chunk_id
- 缺失 page/section 时应优雅降级，而不是抛出 KeyError。
- 为 ContextBuilder 和引用格式新增单元测试。

### 不在范围内

- 不调用 DeepSeek。
- 不实现答案生成 Prompt。
- 不修改 Retriever 排序算法。
- 不做 Tokenizer 精确 token 计数，除非项目已有可复用工具。
- 不实现前端来源展示。
- 不实现 Reranker。

## 约束

- 引用信息必须来自 `SearchHit.metadata` / Chunk 元数据，禁止从正文猜测页码或章节。
- 不得把所有 metadata 原样暴露给 LLM；只保留问答所需字段。
- 上下文超预算时应按检索顺序截断，不能随机丢弃。
- 单个超长 Chunk 的处理行为必须明确：截断、跳过或局部保留需有测试。
- `sources` 顺序必须与上下文编号一致。
- 不引入与前端绑定的展示对象。
- 不修改 Day 1 SearchHit 模型，除非确有必要且保持兼容。

## 验证方式

### 自动化测试

至少覆盖：

1. 多个 SearchHit 被转换成带 `[S1]`、`[S2]` 编号的上下文。
2. PDF 来源正确包含页码。
3. Markdown 来源正确包含 section 或 heading_path。
4. 重复 Chunk 被去重。
5. 超过预算时按顺序截断。
6. 缺失页码/章节时仍可生成来源。
7. 空检索结果返回稳定空结构。
8. sources 与 used_chunk_ids 顺序一致。

建议命令：

```bash
uv run pytest backend/tests/test_context_builder.py -q
```

若测试目录尚无该文件，应创建它。

### 手工检查

构造一组混合 PDF/Markdown SearchHit，打印最终 context 和 sources，确认：

- 编号一一对应；
- 引用可定位；
- 不包含重复块；
- 长度预算有效。

## 最终交付

- `backend/src/rag/context_builder.py`
- 必要的最小 Schema
- `backend/tests/test_context_builder.py`
- 完成说明：
  - 上下文预算策略
  - 去重规则
  - PDF/Markdown 引用格式
  - 测试命令与结果
