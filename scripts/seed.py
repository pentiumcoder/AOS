"""Prepare a fresh stack for the demo: schema, benchmark table and the demo user's memories."""

import argparse

from aos.db import init_db
from aos.memory.longterm import LongTermMemory
from aos.schemas.memory import MemoryItem
from aos.tools.builtin.demo_data import ensure_demo_data

MEMORIES = [
    MemoryItem(
        kind="approach",
        outcome="failure",
        importance=0.8,
        text=(
            "When comparing open-source vector databases, compute throughput, latency and cost "
            "from our benchmark data with db_query; figures taken from web search were "
            "rejected in an earlier review."
        ),
        tags=["research_report"],
    ),
    MemoryItem(
        kind="preference",
        importance=0.7,
        text="Email executive summaries to the team as bullet points of at most 200 words.",
    ),
    MemoryItem(
        kind="task_episode",
        outcome="success",
        importance=0.5,
        text=(
            "Task: Compare open-source vector databases on our benchmark data for the search "
            "team\nPlan (research_report): research, data_analysis, writing after s1+s2\n"
            "Outcome: delivered with 1 revision(s) and 0 failed attempt(s)"
        ),
        tags=["research_report"],
    ),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default="demo")
    args = parser.parse_args()

    init_db()
    ensure_demo_data()
    store = LongTermMemory()
    for item in MEMORIES:
        memory, merged = store.add(args.user, item)
        print(f"{'kept' if merged else 'added'} {memory.kind}: {memory.text[:70]}")
    print(f"{len(store.list_user(args.user))} memories for {args.user}")


if __name__ == "__main__":
    main()
