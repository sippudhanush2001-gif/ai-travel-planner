"""A small, self-contained ReAct-style agent runner.

It is intentionally *not* built on ``create_react_agent`` so that everything is
transparent and provider-independent: the loop binds tools to the model, calls
the model, executes each requested tool, and loops until the model produces a
final answer (or hits the iteration cap).

Works with any ``BaseChatModel`` — including the offline ``MockChatModel``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import BaseTool


@dataclass
class AgentResult:
    """Outcome of one agent run."""

    content: str
    steps: int = 0
    tool_outputs: dict[str, str] = field(default_factory=dict)
    error: str | None = None


class ReActAgent:
    def __init__(
        self,
        *,
        name: str,
        model: Any,
        tools: list[BaseTool],
        system_prompt: str,
        max_iterations: int = 6,
    ) -> None:
        self.name = name
        self.model = model
        self.tools = tools
        self.tools_by_name = {t.name: t for t in tools}
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations

    def run(self, *messages: str) -> AgentResult:
        """Run the agent with the given payload strings (e.g. JSON payloads)."""
        history: list[BaseMessage] = [SystemMessage(content=self.system_prompt)]
        for text in messages:
            history.append(HumanMessage(content=text))

        bound = self.model.bind_tools(self.tools)
        tool_outputs: dict[str, str] = {}

        for step in range(self.max_iterations):
            try:
                ai: AIMessage = bound.invoke(history)
            except Exception as exc:  # noqa: BLE001 - surface to caller
                return AgentResult(
                    content="",
                    steps=step + 1,
                    tool_outputs=tool_outputs,
                    error=f"model error: {type(exc).__name__}: {exc}",
                )
            history.append(ai)

            if not getattr(ai, "tool_calls", None):
                return AgentResult(
                    content=ai.content if isinstance(ai.content, str) else "",
                    steps=step + 1,
                    tool_outputs=tool_outputs,
                )

            for tc in ai.tool_calls:
                name = tc.get("name") or ""
                args = tc.get("args") or {}
                tool = self.tools_by_name.get(name)
                if tool is None:
                    tool_message = ToolMessage(
                        content=f"Tool '{name}' is not available.",
                        tool_call_id=tc.get("id", ""),
                        name=name,
                    )
                    history.append(tool_message)
                    continue
                try:
                    output = tool.invoke(args)
                except Exception as exc:  # noqa: BLE001
                    output = f"Tool error: {type(exc).__name__}: {exc}"
                output = output if isinstance(output, str) else json_dumps(output)
                history.append(
                    ToolMessage(content=output, tool_call_id=tc.get("id", ""), name=name)
                )
                tool_outputs[name] = output

        return AgentResult(
            content="",
            steps=self.max_iterations,
            tool_outputs=tool_outputs,
            error=f"hit max iterations ({self.max_iterations})",
        )


def json_dumps(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, default=str)