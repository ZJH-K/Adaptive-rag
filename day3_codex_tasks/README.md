# Adaptive RAG Day 3 Codex Task Pack

## 包含内容

```text
Adaptive_RAG_Day3_Codex_Task_Pack/
├── Day3_Development_Plan.md
├── README.md
└── codex_tasks/
    ├── task_01_agent_state_and_prompts.md
    ├── task_02_router_and_direct_answer.md
    ├── task_03_query_rewrite.md
    ├── task_04_retrieve_and_generate_nodes.md
    └── task_05_langgraph_integration_and_acceptance.md
```

## 使用方式

1. 将整个目录放入 Adaptive RAG 项目仓库，或单独复制所需任务文件。
2. 开始 Day 3 前先阅读 `Day3_Development_Plan.md`。
3. 每次只把一个 `codex_tasks/task_*.md` 交给 Codex。
4. Codex 完成后，由开发者 Review、运行验证命令并验收。
5. 当前任务未通过，不进入下一个任务。

## 推荐顺序

```text
Task 01
   ↓
Task 02
   ↓
Task 03
   ↓
Task 04
   ↓
Task 05
```

Task 02 和 Task 03 技术上可在 Task 01 后并行，但单人 Review 场景建议顺序执行。
