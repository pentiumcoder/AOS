import math
import time

from aos.config import get_settings
from aos.schemas.memory import StoredMemory

# Half-life multipliers relative to MEMORY_HALF_LIFE_DAYS: preferences and human decisions
# stay relevant much longer than individual task episodes.
HALF_LIFE_FACTOR = {"preference": 6.0, "human_decision": 3.0}
SECONDS_PER_DAY = 86_400


def importance(memory: StoredMemory) -> float:
    return min(1.0, memory.importance + 0.1 * math.log1p(memory.access_count))


def decay(memory: StoredMemory, now: float | None = None) -> float:
    half_life = get_settings().memory_half_life_days * HALF_LIFE_FACTOR.get(memory.kind, 1.0)
    idle_days = max(0.0, ((now or time.time()) - memory.last_accessed_at) / SECONDS_PER_DAY)
    return 0.5 ** (idle_days / half_life)


def effective_importance(memory: StoredMemory, now: float | None = None) -> float:
    return importance(memory) * decay(memory, now)


def rank(memory: StoredMemory, now: float | None = None) -> float:
    return (memory.similarity or 0.0) * (0.7 + 0.3 * effective_importance(memory, now))
