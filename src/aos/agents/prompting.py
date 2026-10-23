import re
from functools import lru_cache
from pathlib import Path

PROMPT_DIR = Path(__file__).parent / "prompts"
_TOKEN = re.compile(r"\{\{\s*(\w+)\s*\}\}")


@lru_cache
def load_prompt(name: str) -> str:
    return (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8").strip()


def render(name: str, **values: object) -> str:
    """Fill {{placeholders}} that have a value and leave the rest untouched."""

    def substitute(match: re.Match[str]) -> str:
        key = match.group(1)
        return str(values[key]) if key in values else match.group(0)

    return _TOKEN.sub(substitute, load_prompt(name))


def section(title: str, body: str | None) -> str:
    return f"\n\n{title}:\n{body.strip()}" if body and body.strip() else ""
