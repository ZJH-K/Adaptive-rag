"""Central prompt templates for routing and query rewriting."""

import json
from typing import Any


ROUTER_PROMPT = """你是技术文档问答系统的检索路由器。

请判断当前问题是否必须依赖当前知识库（包括用户上传文档和内置文档）才能可靠回答。

判断规则：
- 通用知识问题，例如常见概念解释或编程语言基础，通常不需要检索。
- 提到“文档中”“我上传的”“该项目”“上面提到”“它”等文档或上下文依赖时，需要检索。
- 询问当前知识库中特定机制、配置、限制、专有内容，或要求精确引用时，需要检索。
- 聊天历史只用于理解指代，不要把通用问题误判为文档问题。

当前问题：
{question}

聊天历史（JSON）：
{chat_history}

只输出一个符合以下结构的 JSON 对象，不要输出 Markdown 代码块或额外解释：
{{"need_retrieval": true, "reason": "简短、可观察的路由原因"}}

need_retrieval 必须是布尔值。reason 只描述判断依据，不要输出长篇推理过程或思维链。
"""


QUERY_REWRITE_PROMPT = """你是技术文档检索查询改写器。

结合聊天历史，将当前问题改写为一个无需读取聊天历史也能理解的独立检索问题。

改写约束：
- 补全“它”“上面提到的”等指代，并加入必要实体。
- 保留用户原意，不改变问题范围。
- 不猜测事实，不添加当前问题或聊天历史中没有的结论。
- 只生成一个独立问题，不生成多个候选查询。

当前问题：
{question}

聊天历史（JSON）：
{chat_history}

只输出一个符合以下结构的 JSON 对象，不要输出 Markdown 代码块或额外解释：
{{"rewritten_query": "一个独立的检索问题"}}
"""


DIRECT_ANSWER_PROMPT = """你是一个准确、简洁的通用问答助手。
请直接回答用户的通用知识问题；不要声称查阅了知识库或编造文档引用。"""


def format_router_prompt(
    question: str,
    chat_history: list[dict[str, Any]] | None = None,
) -> str:
    """Render the router prompt with the current question and chat history."""

    return ROUTER_PROMPT.format(
        question=question,
        chat_history=_serialize_history(chat_history),
    )


def format_query_rewrite_prompt(
    question: str,
    chat_history: list[dict[str, Any]] | None = None,
) -> str:
    """Render the rewrite prompt with the current question and chat history."""

    return QUERY_REWRITE_PROMPT.format(
        question=question,
        chat_history=_serialize_history(chat_history),
    )


def _serialize_history(chat_history: list[dict[str, Any]] | None) -> str:
    return json.dumps(chat_history or [], ensure_ascii=False)
