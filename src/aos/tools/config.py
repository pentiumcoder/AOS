from functools import lru_cache
from typing import Any

import yaml

from aos.config import get_settings


@lru_cache
def tool_config() -> dict[str, Any]:
    path = get_settings().config_dir / "tools.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def http_allowlist() -> list[str]:
    return list(tool_config().get("http_allowlist", []))
