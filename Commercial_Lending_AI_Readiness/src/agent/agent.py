"""LendingComplianceAgent: Claude-powered agentic loop with tool use."""
from dataclasses import dataclass, field
from datetime import date
import anthropic
from src.agent import tool_registry
from src.agent.prompts import SYSTEM_PROMPT
from config.settings import CLAUDE_MODEL


@dataclass
class AgentResult:
    final_response: str
    tool_calls: list[dict] = field(default_factory=list)
    turns: int = 0
    truncated: bool = False


class LendingComplianceAgent:
    def __init__(self, client: anthropic.Anthropic):
        self.client = client

    def run(self, user_query: str, max_turns: int = 10, verbose: bool = True) -> AgentResult:
        system = SYSTEM_PROMPT.format(today=date.today().isoformat())
        messages: list[dict] = [{"role": "user", "content": user_query}]
        tool_calls_log: list[dict] = []
        turns = 0

        while turns < max_turns:
            turns += 1
            response = self.client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=4096,
                system=system,
                tools=tool_registry.TOOL_DEFINITIONS,
                messages=messages,
            )

            # Collect assistant message content
            assistant_content = response.content
            messages.append({"role": "assistant", "content": assistant_content})

            if response.stop_reason == "end_turn":
                final_text = next(
                    (b.text for b in assistant_content if hasattr(b, "text")), ""
                )
                return AgentResult(
                    final_response=final_text,
                    tool_calls=tool_calls_log,
                    turns=turns,
                )

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in assistant_content:
                    if block.type != "tool_use":
                        continue

                    tool_name = block.name
                    tool_input = block.input

                    if verbose:
                        args_preview = ", ".join(
                            f"{k}={repr(v)}" for k, v in list(tool_input.items())[:3]
                        )
                        print(f"    [tool] {tool_name}({args_preview})")

                    result_str = tool_registry.dispatch(tool_name, tool_input)
                    tool_calls_log.append({
                        "tool": tool_name,
                        "input": tool_input,
                        "result_preview": result_str[:200],
                    })

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_str,
                    })

                messages.append({"role": "user", "content": tool_results})

            else:
                # Unexpected stop reason
                break

        final_text = next(
            (
                b.text
                for msg in reversed(messages)
                if msg["role"] == "assistant"
                for b in (msg["content"] if isinstance(msg["content"], list) else [])
                if hasattr(b, "text")
            ),
            "Agent reached maximum turns without completing.",
        )
        return AgentResult(
            final_response=final_text,
            tool_calls=tool_calls_log,
            turns=turns,
            truncated=True,
        )
