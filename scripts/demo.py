"""Run the showcase task against a running API and narrate what the agents do."""

import argparse
import os
import sys
import time
from typing import Any

import httpx

SHOWCASE = (
    "Research the top 3 open-source vector databases, compare their performance and pricing "
    "using our benchmark data, write an executive summary, and email it to the team."
)


class Demo:
    def __init__(self, api_url: str, auto_approve: bool) -> None:
        self.client = httpx.Client(base_url=api_url, timeout=60)
        self.auto_approve = auto_approve
        self.printed = 0
        self.decided: set[str] = set()

    def call(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self.client.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()

    def run(self, request: str, user: str) -> int:
        health = self.call("GET", "/health")
        print(f"API {health['status']} · {health['llm_mode']} models · {health['storage_mode']}")
        accepted = self.call("POST", "/tasks", json={"request": request, "user_id": user})
        print(f"Task {accepted['task_id']}\n")
        while True:
            task = self.call("GET", f"/tasks/{accepted['task_id']}")
            run = task.get("run") or {}
            self.show_events(run.get("events", []))
            if task["status"] in ("completed", "failed"):
                return self.finish(task, run)
            for waiting in run.get("pending_escalations", []):
                self.escalation(waiting["id"])
            time.sleep(1)

    def show_events(self, events: list[dict[str, Any]]) -> None:
        for item in events[self.printed :]:
            print(f"  [{item['node']}] {item['message']}")
        self.printed = max(self.printed, len(events))

    def escalation(self, escalation_id: str) -> None:
        if escalation_id in self.decided:
            return
        detail = self.call("GET", f"/escalations/{escalation_id}")
        print(f"\n  Waiting for a human: {detail['level']} · {detail['reason']}")
        if detail.get("proposed_action"):
            action = detail["proposed_action"]
            print(f"  Proposed {action['tool']} with {action['args']}")
        if not self.auto_approve:
            print("  Decide in the review console; this script continues once you do.\n")
            self.decided.add(escalation_id)
            return
        self.call(
            "POST",
            f"/escalations/{escalation_id}/decision",
            json={"action": "approve", "reviewer": "demo", "comment": "approved by demo script"},
        )
        print("  Approved by the demo script.\n")
        self.decided.add(escalation_id)

    def finish(self, task: dict[str, Any], run: dict[str, Any]) -> int:
        print(f"\nRun {task['status']}.")
        for influence in (run.get("plan") or {}).get("memory_influence", []):
            print(f"  Memory used: {influence['how_used']}")
        if task.get("final_output"):
            print("\n" + task["final_output"] + "\n")
        metrics = self.call("GET", f"/runs/{run['id']}/metrics")
        trace = self.call("GET", f"/runs/{run['id']}/trace")
        llm = metrics["llm"]
        priced = " (simulated prices)" if llm["simulated_prices"] else ""
        print(
            f"{llm['calls']} model calls, {llm['input_tokens'] + llm['output_tokens']:,} tokens, "
            f"${llm['cost_usd']:.4f}{priced}; {metrics['tools']['calls']} tool calls; "
            f"{trace['span_count']} spans; human review {metrics['human_review_seconds']}s"
        )
        print("Review console: http://localhost:8501 · trace explorer: Trace Explorer page")
        return 0 if task["status"] == "completed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default=os.environ.get("API_URL", "http://localhost:8000"))
    parser.add_argument("--user", default="demo")
    parser.add_argument("--request", default=SHOWCASE)
    parser.add_argument("--auto-approve", action="store_true")
    args = parser.parse_args()
    return Demo(args.api, args.auto_approve).run(args.request, args.user)


if __name__ == "__main__":
    sys.exit(main())
