import json
from dataclasses import dataclass, field
from typing import Any

from aos import context
from aos.agents.prompting import load_prompt, render, section
from aos.config import get_settings
from aos.llm import LLMError, Message, ToolCall, ToolDef, get_llm
from aos.schemas import ProposedAction, SpecialistOutput, SpecialistResult, Subtask
from aos.tools import policy
from aos.tools.registry import ToolRegistry, get_registry

QUEUED = "Queued: {tool} requires approval and runs after review. Do not call it again."
REPEATED = (
    "You already ran {tool} with these arguments and its result is above. "
    "Use it, or give your final answer."
)
MAX_EVIDENCE = 6
EVIDENCE_CHARS = 1500


@dataclass
class Attempt:
    subtask: Subtask
    request: str
    number: int
    offered: set[str]
    proposed: list[ProposedAction] = field(default_factory=list)
    used: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    seen_calls: set[str] = field(default_factory=set)


class SpecialistAgent:
    name: str = ""
    description: str = ""

    def __init__(self, registry: ToolRegistry | None = None) -> None:
        self._registry = registry

    @property
    def registry(self) -> ToolRegistry:
        return self._registry or get_registry()

    def system_prompt(self) -> str:
        return f"{render(f'specialist_{self.name}')}\n\n{load_prompt('specialist_rules')}"

    def offered_tools(self, subtask: Subtask, request: str) -> list[ToolDef]:
        """Tools for this subtask. Sensitive ones need both the plan and the request to ask."""
        registry = self.registry
        return [
            tool
            for tool in registry.list_for(self.name)
            if not registry.is_sensitive(tool.name)
            or (tool.name in subtask.actions and policy.requested(tool.name, request))
        ]

    def run(
        self,
        subtask: Subtask,
        *,
        request: str,
        dep_outputs: dict[str, str],
        feedback: str | None = None,
        approach_hint: str | None = None,
        attempt: int = 1,
    ) -> SpecialistResult:
        max_steps = get_settings().specialist_max_steps
        tools = self.offered_tools(subtask, request)
        state = Attempt(subtask, request, attempt, offered={tool.name for tool in tools})
        messages = [
            Message.user(
                self.task_prompt(subtask, request, dep_outputs, feedback, approach_hint, state)
            )
        ]
        meta: dict[str, Any] = {
            "purpose": "specialist",
            "agent": self.name,
            "subtask_id": subtask.id,
            "subtask": subtask.description,
            "attempt": attempt,
            "request": request,
            "dep_outputs": dep_outputs,
            "feedback": feedback or "",
        }
        with context.bind(agent=self.name, attempt=attempt):
            try:
                llm = get_llm(self.name, subtask.complexity)
                for _ in range(max_steps):
                    result = llm.complete(
                        messages,
                        system=self.system_prompt(),
                        tools=tools,
                        schema=SpecialistOutput,
                        max_tokens=4096,
                        meta=meta,
                    )
                    if result.parsed is not None:
                        return self._finish(state, result.parsed)
                    messages.append(Message.assistant(result.text, result.tool_calls))
                    for call in result.tool_calls:
                        content = self._execute(call, result.text, state)
                        messages.append(Message.tool(call.id, call.name, content))
                    # A queued action is final for this attempt; withdrawing the tool stops
                    # models from queueing it again instead of answering.
                    queued = {action.tool for action in state.proposed}
                    tools = [tool for tool in tools if tool.name not in queued]
            except LLMError as exc:
                return self._failed(state, f"model unavailable: {exc}")
        return self._failed(state, f"no final answer within {max_steps} steps")

    def task_prompt(
        self,
        subtask: Subtask,
        request: str,
        dep_outputs: dict[str, str],
        feedback: str | None,
        approach_hint: str | None,
        state: Attempt | None = None,
    ) -> str:
        inputs = "\n".join(f"- {key}: {value}" for key, value in subtask.inputs.items())
        upstream = "\n\n".join(f"### {sid}\n{output}" for sid, output in dep_outputs.items())
        contacts = (
            policy.contacts_text(request) if state and "send_email" in state.offered else None
        )
        return (
            f"Overall request:\n{request}\n\n"
            f"Your subtask ({subtask.id}):\n{subtask.description}\n\n"
            f"Expected output:\n{subtask.expected_output}"
            + section("Inputs", inputs)
            + section("Outputs of earlier subtasks", upstream)
            + section("Contacts you may email", contacts)
            + section("Reviewer feedback on your previous attempt", feedback)
            + section("Approach hint", approach_hint or subtask.approach_hint)
        )

    def _execute(self, call: ToolCall, reasoning: str, state: Attempt) -> str:
        registry = self.registry
        if not registry.is_sensitive(call.name):
            key = f"{call.name}:{json.dumps(call.args, sort_keys=True, default=str)}"
            if key in state.seen_calls:
                return REPEATED.format(tool=call.name)
            state.seen_calls.add(key)
            outcome = registry.invoke(self.name, call.name, call.args)
            if outcome.success:
                state.used.append(call.name)
                args = json.dumps(call.args, default=str)[:300]
                state.evidence.append(f"{call.name} {args}\n-> {outcome.as_text(EVIDENCE_CHARS)}")
            return outcome.as_text()
        return self._propose(call, reasoning, state)

    def _propose(self, call: ToolCall, reasoning: str, state: Attempt) -> str:
        if call.name not in state.offered:
            return f"ERROR: {call.name} is not available for this subtask"
        if any(action.tool == call.name for action in state.proposed):
            return f"ERROR: {call.name} is already queued for this subtask; give your final answer."
        if problem := self.registry.validate_args(call.name, call.args):
            return f"ERROR: {problem}"
        if problem := policy.check_action(call.name, call.args, state.request):
            return f"ERROR: {problem}"
        state.proposed.append(
            ProposedAction(
                id=f"{state.subtask.id}-a{len(state.proposed) + 1}",
                subtask_id=state.subtask.id,
                agent=self.name,
                tool=call.name,
                args=call.args,
                reasoning=reasoning,
            )
        )
        return QUEUED.format(tool=call.name)

    def _finish(self, state: Attempt, output: SpecialistOutput) -> SpecialistResult:
        if not output.completed:
            return self._failed(state, output.blocker or "reported as not completed")
        return SpecialistResult(
            subtask_id=state.subtask.id,
            specialist=self.name,
            status="success",
            output=output.output,
            data=output.data,
            confidence=output.confidence,
            proposed_actions=state.proposed,
            tools_used=sorted(set(state.used)),
            evidence=state.evidence[-MAX_EVIDENCE:],
            attempt=state.number,
        )

    def _failed(self, state: Attempt, error: str) -> SpecialistResult:
        return SpecialistResult(
            subtask_id=state.subtask.id,
            specialist=self.name,
            status="failed",
            proposed_actions=state.proposed,
            tools_used=sorted(set(state.used)),
            evidence=state.evidence[-MAX_EVIDENCE:],
            attempt=state.number,
            error=error,
        )
