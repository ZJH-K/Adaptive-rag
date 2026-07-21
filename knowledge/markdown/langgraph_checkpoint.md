# LangGraph Checkpoint Quick Guide

LangGraph uses a checkpointer to save graph state between execution steps.
Development can use an in-memory checkpointer; persistent deployments should use
a database-backed checkpointer.

## Required conversation identifier

Every invocation that shares persisted state must provide the same `thread_id` in
the configurable runtime options. The checkpointer uses it to locate conversation
state. A missing or changing `thread_id` starts an independent history.

## Configuration summary

Create the checkpointer, pass it when compiling the graph, and invoke the compiled
graph with a stable `thread_id`. Choose identifiers that are stable within one
conversation and isolated from other conversations.
