import argparse
import sys
from typing import Any

from aos.config import get_settings
from aos.logging import setup_logging


def cmd_db(args: argparse.Namespace) -> int:
    from aos.db import init_db, reset_db
    from aos.tools.builtin.demo_data import ensure_demo_data, reset_demo_data

    if args.action == "reset":
        reset_db()
        reset_demo_data()
    else:
        init_db()
    ensure_demo_data()
    print(f"database {'reset' if args.action == 'reset' else 'initialised'}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from aos.db import init_db
    from aos.graph.runner import create_task, execute_run

    init_db()
    task_id, run_id = create_task(args.request, args.user, args.review)
    if not args.sync:
        from aos.worker.tasks import run_task

        run_task.delay(run_id)
        print(f"queued task {task_id} (run {run_id})")
        return 0

    print(f"task {task_id} (run {run_id})\n")
    if args.auto_approve:
        from aos.graph.runner import run_to_completion
        from aos.schemas.escalation import HumanDecision

        def approve(escalation: dict[str, Any]) -> HumanDecision:
            print(
                f"[auto-approve] {escalation['level']} {escalation['trigger']}: "
                f"{escalation['reason']}"
            )
            return HumanDecision(action="approve", reviewer="cli", comment="auto-approved")

        final = run_to_completion(run_id, approve)
    else:
        final = execute_run(run_id)
    _print_report(final, run_id)
    if final.get("__interrupt__"):
        return 0
    return 0 if final.get("final_output") else 1


def cmd_llm_smoke(args: argparse.Namespace) -> int:
    from pydantic import BaseModel

    from aos.llm import Message
    from aos.llm.router import LLMClient, providers_for

    class Ping(BaseModel):
        answer: str

    settings = get_settings()
    print(f"LLM_MODE={settings.llm_mode}")
    failed = False
    for role in ("supervisor", "research", "reviewer"):
        chain = providers_for(role)
        print(f"{role}: {', '.join(repr(p) for p in chain) or 'no provider available'}")
        if not chain:
            failed = True
            continue
        try:
            result = LLMClient(role, chain, retries=0).complete(
                [Message.user("Reply with the single word ready.")],
                schema=Ping,
                max_tokens=50,
                meta={"purpose": "smoke"},
            )
            print(
                f"  -> {result.provider}:{result.model} {result.parsed!r} "
                f"({result.latency_ms:.0f} ms)"
            )
        except Exception as exc:
            failed = True
            print(f"  -> failed: {exc}")
    return 1 if failed else 0


def cmd_memory(args: argparse.Namespace) -> int:
    from aos.memory.longterm import LongTermMemory
    from aos.memory.management import forget_user, maintain
    from aos.memory.scoring import effective_importance

    if args.action == "maintain":
        print(maintain(args.user).model_dump_json(indent=2))
        return 0
    if args.user is None:
        print("--user is required")
        return 2
    if args.action == "forget":
        print(forget_user(args.user))
        return 0
    for memory in LongTermMemory().list_user(args.user):
        print(f"[{memory.kind}] {effective_importance(memory):.2f} {memory.text[:100]}")
    return 0


def _print_report(final: dict[str, Any], run_id: str) -> None:
    from aos.db import session_scope
    from aos.db.models import OutboxMessage

    for item in final.get("events", []):
        print(f"[{item['node']}] {item['message']}")
    if final.get("__interrupt__"):
        waiting = final["__interrupt__"][0].value
        print(
            f"\npaused for a human: {waiting['level']} {waiting['trigger']} - {waiting['reason']}"
            f"\ndecide with POST /escalations/{waiting['escalation_id']}/decision"
        )
        return
    print("\n" + "=" * 72)
    print(final.get("final_output") or f"no deliverable: {final.get('error')}")
    print("=" * 72)
    with session_scope() as session:
        for message in session.query(OutboxMessage).filter_by(run_id=run_id):
            print(
                f"\noutbox: to {message.recipient} | {message.subject} ({len(message.body)} chars)"
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aos")
    parser.add_argument("-v", "--verbose", action="store_true", help="print JSON logs")
    sub = parser.add_subparsers(dest="command", required=True)

    db = sub.add_parser("db", help="create or reset the database schema")
    db.add_argument("action", choices=["init", "reset"])
    db.set_defaults(func=cmd_db)

    run = sub.add_parser("run", help="submit a task")
    run.add_argument("request")
    run.add_argument("--user", default="default")
    run.add_argument("--review", action="store_true", help="require human review of the result")
    run.add_argument("--sync", action="store_true", help="run in this process instead of Celery")
    run.add_argument(
        "--auto-approve", action="store_true", help="approve every escalation (with --sync)"
    )
    run.set_defaults(func=cmd_run)

    smoke = sub.add_parser("llm-smoke", help="check that each role can reach a model")
    smoke.set_defaults(func=cmd_llm_smoke)

    memory = sub.add_parser("memory", help="inspect or maintain long-term memory")
    memory.add_argument("action", choices=["maintain", "list", "forget"])
    memory.add_argument("--user", default=None)
    memory.set_defaults(func=cmd_memory)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(get_settings().log_level if args.verbose else "WARNING")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
