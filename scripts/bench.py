"""Measure run time, throughput, API read latency and replay against a running stack."""

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx
from demo import SHOWCASE

FINISHED = ("completed", "failed")


class Client:
    def __init__(self, api_url: str, user: str) -> None:
        self.http = httpx.Client(base_url=api_url, timeout=120)
        self.user = user

    def call(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self.http.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()

    def run(self, request: str) -> dict[str, Any]:
        """Submit a task, approve whatever it asks, and return its server-side metrics."""
        started = time.perf_counter()
        task_id = self.call("POST", "/tasks", json={"request": request, "user_id": self.user})[
            "task_id"
        ]
        decided: set[str] = set()
        while True:
            task = self.call("GET", f"/tasks/{task_id}")
            if task["status"] in FINISHED:
                break
            for waiting in (task.get("run") or {}).get("pending_escalations", []):
                if waiting["id"] not in decided:
                    self.approve(waiting["id"])
                    decided.add(waiting["id"])
            time.sleep(0.2)
        metrics = self.call("GET", f"/runs/{task['run']['id']}/metrics")
        return {
            "status": task["status"],
            "run_id": task["run"]["id"],
            "client_seconds": time.perf_counter() - started,
            "agent_seconds": metrics["agent_seconds"],
            "calls": metrics["llm"]["calls"],
            "tokens": metrics["llm"]["input_tokens"] + metrics["llm"]["output_tokens"],
            "tool_calls": metrics["tools"]["calls"],
        }

    def approve(self, escalation_id: str) -> None:
        level = self.call("GET", f"/escalations/{escalation_id}")["level"]
        decision = (
            {"action": "take_over", "payload": "Provided by the benchmark", "reviewer": "bench"}
            if level == "TAKE_OVER"
            else {"action": "approve", "reviewer": "bench"}
        )
        self.call("POST", f"/escalations/{escalation_id}/decision", json=decision)

    def timed_get(self, path: str) -> float:
        started = time.perf_counter()
        self.call("GET", path)
        return (time.perf_counter() - started) * 1000

    def replay(self, run_id: str) -> dict[str, Any]:
        started = time.perf_counter()
        accepted = self.call(
            "POST", f"/runs/{run_id}/replay", json={"mode": "recorded", "overrides": {}}
        )
        # The task reads completed a moment before the worker stores the replay summary.
        while True:
            status = self.call("GET", f"/tasks/{accepted['task_id']}")["status"]
            report = self.call("GET", f"/runs/{run_id}/compare/{accepted['run_id']}")
            if status == "failed" or (status == "completed" and report["replay"]):
                break
            time.sleep(0.2)
        return {"seconds": time.perf_counter() - started, **(report["replay"] or {})}


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def spread(values: list[float], unit: str, digits: int = 1) -> str:
    return (
        " / ".join(f"{percentile(values, q):.{digits}f} {unit}" for q in (0.5, 0.95))
        + f" (n={len(values)})"
    )


def sequential(client: Client, request: str, runs: int) -> list[dict[str, Any]]:
    results = [client.run(request) for _ in range(runs)]
    failed = [r for r in results if r["status"] != "completed"]
    print(f"\nSequential runs: {runs - len(failed)}/{runs} completed")
    print(f"  agent time p50 / p95:  {spread([r['agent_seconds'] for r in results], 's')}")
    print(f"  client time p50 / p95: {spread([r['client_seconds'] for r in results], 's')}")
    first = results[0]
    print(
        f"  per run: {first['calls']} model calls, {first['tokens']:,} tokens, "
        f"{first['tool_calls']} tool calls"
    )
    return results


def concurrent(api_url: str, user: str, request: str, tasks: int, parallel: int) -> None:
    clients = [Client(api_url, user) for _ in range(parallel)]
    started = time.perf_counter()
    with ThreadPoolExecutor(parallel) as pool:
        results = list(pool.map(lambda i: clients[i % parallel].run(request), range(tasks)))
    wall = time.perf_counter() - started
    done = sum(r["status"] == "completed" for r in results)
    print(f"\nConcurrent: {tasks} tasks, {parallel} submitted at a time")
    print(f"  {done}/{tasks} completed in {wall:.1f} s = {tasks / wall * 60:.1f} runs/min")
    print(f"  client time p50 / p95: {spread([r['client_seconds'] for r in results], 's')}")


def reads(client: Client, run_id: str, samples: int) -> None:
    task_id = client.call("GET", "/tasks", params={"limit": 1})[0]["id"]
    paths = {
        "GET /tasks?limit=20": "/tasks?limit=20",
        "GET /tasks/{id}": f"/tasks/{task_id}",
        "GET /runs/{id}/trace": f"/runs/{run_id}/trace",
        "GET /runs/{id}/metrics": f"/runs/{run_id}/metrics",
        "GET /metrics/summary": "/metrics/summary?days=7",
    }
    print(f"\nAPI read latency, p50 / p95 over {samples} calls")
    for label, path in paths.items():
        client.timed_get(path)
        timings = [client.timed_get(path) for _ in range(samples)]
        print(f"  {label:<24} {spread(timings, 'ms')}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default=os.environ.get("API_URL", "http://localhost:8000"))
    parser.add_argument("--user", default="bench")
    parser.add_argument("--request", default=SHOWCASE)
    parser.add_argument("--runs", type=int, default=10, help="sequential runs")
    parser.add_argument("--tasks", type=int, default=20, help="tasks in the concurrent phase")
    parser.add_argument("--parallel", type=int, default=8, help="tasks in flight at once")
    parser.add_argument("--samples", type=int, default=50, help="calls per read endpoint")
    parser.add_argument("--skip", nargs="*", default=[], choices=["concurrent", "reads", "replay"])
    args = parser.parse_args()

    client = Client(args.api, args.user)
    health = client.call("GET", "/health")
    print(f"API {health['status']} · {health['llm_mode']} models · {health['storage_mode']}")

    results = sequential(client, args.request, args.runs)
    if "concurrent" not in args.skip:
        concurrent(args.api, args.user, args.request, args.tasks, args.parallel)
    if "reads" not in args.skip:
        reads(client, results[-1]["run_id"], args.samples)
    if "replay" not in args.skip:
        replay = client.replay(results[-1]["run_id"])
        print(
            f"\nRecorded replay: {replay['seconds']:.1f} s, "
            f"{replay.get('replayed_calls', 0)} calls reused, {replay.get('fresh_calls', 0)} fresh"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
