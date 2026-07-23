# Adaptive RAG Day 1 Codex 任务包

本任务包用于按照“开发者负责 Review 和验收、Codex 负责代码实现”的方式完成 Adaptive RAG 项目 Day 1。

## 文件结构

```text
Adaptive_RAG_Day1_Codex_Package/
├── README.md
├── Day1_Development_Plan.md
└── codex_tasks/
    ├── Day1_Task01_Project_Setup.md
    ├── Day1_Task02_Parsers.md
    ├── Day1_Task03_Recursive_Chunker.md
    ├── Day1_Task04_Embedding_Client.md
    ├── Day1_Task05_Chroma_VectorStore.md
    ├── Day1_Task06_Ingestion_and_Dense_Retrieval.md
    └── Day1_Task07_Acceptance.md
```

## 使用方式

1. 将 `AGENTS.md` 和 `adaptive_rag_project_technical_spec.md` 放在项目根目录。
2. 先阅读 `Day1_Development_Plan.md`，确认 Day 1 范围和任务依赖。
3. 每次只把一个 `codex_tasks/` 下的任务交给 Codex。
4. Codex 完成后，由开发者执行 Review 和验收。
5. 当前任务未通过验收前，不进入下一个任务。

## 执行顺序

```text
Task 1
  ├── Task 2
  │     └── Task 3
  └── Task 4
          └── Task 5
                  └── Task 6
                          └── Task 7
```

推荐实际执行顺序：

```text
1 → 2 → 3 → 4 → 5 → 6 → 7
```

## 文档职责

- `adaptive_rag_project_technical_spec.md`：项目技术规格和架构边界。
- `AGENTS.md`：Codex 开发行为规范。
- `Day1_Development_Plan.md`：Day 1 总览与进度管理。
- `codex_tasks/*.md`：可直接交给 Codex 的单次执行任务。
