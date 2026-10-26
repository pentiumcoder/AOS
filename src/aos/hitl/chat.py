import json
from typing import Any

from aos import context
from aos.hitl.queue import append_chat, get_escalation
from aos.llm import Message, get_llm

SYSTEM = (
    "You coordinate a team of AI agents. A human reviewer is deciding on an escalation and "
    "asks you questions before choosing. Answer only from the escalation context, quoting "
    "figures and outputs exactly. You cannot take actions or change the run; if asked to, "
    "say that the reviewer decides with the buttons. Be brief."
)
HISTORY_TURNS = 10


def answer(escalation_id: str, question: str) -> dict[str, Any]:
    escalation = get_escalation(escalation_id)
    if escalation is None:
        raise KeyError(escalation_id)
    briefing = {
        "trigger": escalation["trigger"],
        "level": escalation["level"],
        "reason": escalation["reason"],
        "proposed_action": escalation["proposed_action"],
        **escalation["context"],
    }
    messages = [Message.user(f"Escalation context:\n{json.dumps(briefing, default=str)}")]
    messages.append(Message.assistant("Understood. What would you like to know?"))
    for turn in escalation["chat"][-HISTORY_TURNS:]:
        role = "user" if turn["role"] == "reviewer" else "assistant"
        messages.append(Message(role=role, content=turn["content"]))
    messages.append(Message.user(question))
    with context.bind(run_id=escalation["run_id"], agent="coordinator"):
        reply = get_llm("supervisor", "medium").complete(
            messages,
            system=SYSTEM,
            max_tokens=800,
            meta={
                "purpose": "escalation_chat",
                "request": escalation["context"]["task"]["request"],
                "reason": escalation["reason"],
                "question": question,
            },
        )
    text = reply.text.strip()
    chat = append_chat(
        escalation_id,
        {"role": "reviewer", "content": question},
        {"role": "agent", "content": text},
    )
    return {"answer": text, "chat": chat}
