# 简历项目描述

## 2–3 行版本

基于 FastAPI、LangGraph 与 Streamlit 实现面向 PDF/Markdown 的自适应 RAG，支持
结构感知切分、Chroma + BM25 混合召回、RRF、可降级 Reranker、SSE 流式回答和
页码/章节级引用。构建 24 条人工证据标注数据集与 A/B/C/D Runner，用 Hit@K、
Recall@K、MRR 和延迟定位当前优化策略在小语料上的退化，而非只展示功能。

## 4–5 行版本

设计技术文档 RAG Pipeline，以 LangGraph Router 在直接回答与检索增强之间路由，
浏览器主链路统一经过一份编译图。实现 PDF 页码感知、Markdown 标题感知和递归
Baseline 切分，组合 Chroma Dense、中文 BM25、RRF 与可选 Reranker，并保证
Context 和 Sources 精确同源。通过 FastAPI SSE 支持真实异步 token、客户端断连取消、
Request/Trace 生命周期与可选 Langfuse Adapter。建立 24 条正式 Evaluation 数据集；
A/B/C 完成、D 跳过，结果诚实显示该小样本上优化组未优于 Baseline。使用非 root
Python 3.11 镜像和单 worker Docker Compose 提供可复现 Demo。

## 使用边界

不要把本项目描述为“生产级高并发”“显著提升召回”或“已完成 Langfuse/Reranker
真实验证”。真实 Reranker 与 Langfuse Smoke 仍为 NOT RUN，Evaluation 规模不足以
支持普适结论。
