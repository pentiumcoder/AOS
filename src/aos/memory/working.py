import json
from datetime import UTC, datetime
from typing import Any

import redis

from aos.db.cache import get_redis

TTL_SECONDS = 24 * 3600


class WorkingMemory:
    """Scratch space shared by every agent of one run. It lives in Redis until the run ends."""

    def __init__(self, run_id: str, client: redis.Redis | None = None) -> None:
        self.run_id = run_id
        self.prefix = f"aos:wm:{run_id}"
        self._redis = client or get_redis()

    def _key(self, part: str) -> str:
        return f"{self.prefix}:{part}"

    def _write(self, key: str, op: str, *args: Any) -> None:
        pipe = self._redis.pipeline()
        getattr(pipe, op)(key, *args)
        # A run that crashes never reaches deliver, so every key expires on its own.
        pipe.expire(key, TTL_SECONDS)
        pipe.execute()

    def set_plan(self, plan: dict[str, Any]) -> None:
        self._write(self._key("plan"), "set", json.dumps(plan))

    def plan(self) -> dict[str, Any] | None:
        raw = self._redis.get(self._key("plan"))
        return json.loads(raw) if raw else None

    def put_output(self, subtask_id: str, output: str, data: dict[str, Any] | None = None) -> None:
        payload = json.dumps({"output": output, "data": data or {}})
        self._write(self._key("outputs"), "hset", subtask_id, payload)

    def get_outputs(self, subtask_ids: list[str]) -> dict[str, str]:
        if not subtask_ids:
            return {}
        raw = self._redis.hmget(self._key("outputs"), subtask_ids)
        pairs = zip(subtask_ids, raw, strict=True)
        return {sid: json.loads(value)["output"] for sid, value in pairs if value}

    def outputs(self) -> dict[str, dict[str, Any]]:
        raw = self._redis.hgetall(self._key("outputs"))
        return {sid: json.loads(value) for sid, value in raw.items()}

    def add_note(self, agent: str, text: str, subtask_id: str | None = None) -> None:
        self._append("notes", {"agent": agent, "subtask_id": subtask_id, "text": text})

    def notes(self) -> list[dict[str, Any]]:
        return self._read_list("notes")

    def log_error(self, source: str, message: str, subtask_id: str | None = None) -> None:
        self._append("errors", {"source": source, "subtask_id": subtask_id, "message": message})

    def errors(self) -> list[dict[str, Any]]:
        return self._read_list("errors")

    def snapshot(self) -> dict[str, Any]:
        return {
            "plan": self.plan(),
            "outputs": self.outputs(),
            "notes": self.notes(),
            "errors": self.errors(),
        }

    def clear(self) -> None:
        self._redis.delete(*(self._key(part) for part in ("plan", "outputs", "notes", "errors")))

    def _append(self, part: str, entry: dict[str, Any]) -> None:
        entry["at"] = datetime.now(UTC).isoformat(timespec="seconds")
        self._write(self._key(part), "rpush", json.dumps(entry))

    def _read_list(self, part: str) -> list[dict[str, Any]]:
        return [json.loads(item) for item in self._redis.lrange(self._key(part), 0, -1)]
