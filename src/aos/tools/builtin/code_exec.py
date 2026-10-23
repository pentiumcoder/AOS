import os
import subprocess
import sys
import tempfile
from pathlib import Path

from pydantic import BaseModel, Field

from aos.tools.base import ToolContext, ToolError

# Not a security boundary: the child runs as the same user. It gets a scratch directory,
# a stripped environment (no API keys) and a hard timeout. Untrusted code needs a real
# sandbox such as gVisor or Firecracker.
PASSTHROUGH_ENV = ("PATH", "SYSTEMROOT", "TEMP", "TMP", "LANG")
OUTPUT_LIMIT = 10_000


class CodeExecInput(BaseModel):
    code: str = Field(min_length=1, max_length=50_000)
    timeout_s: float = Field(default=10, gt=0, le=30)


class CodeExecOutput(BaseModel):
    exit_code: int
    stdout: str
    stderr: str


def code_exec(args: CodeExecInput, ctx: ToolContext) -> CodeExecOutput:
    env = {key: os.environ[key] for key in PASSTHROUGH_ENV if key in os.environ}
    env["PYTHONIOENCODING"] = "utf-8"
    with tempfile.TemporaryDirectory(prefix="aos-exec-") as scratch:
        script = Path(scratch) / "main.py"
        script.write_text(args.code, encoding="utf-8")
        try:
            proc = subprocess.run(
                [sys.executable, "-I", str(script)],
                cwd=scratch,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=args.timeout_s,
            )
        except subprocess.TimeoutExpired as exc:
            raise ToolError(f"code timed out after {args.timeout_s:g}s") from exc
    if proc.returncode != 0:
        tail = proc.stderr.strip().splitlines()[-8:]
        raise ToolError(f"exit code {proc.returncode}: " + "\n".join(tail))
    return CodeExecOutput(
        exit_code=proc.returncode,
        stdout=proc.stdout[:OUTPUT_LIMIT],
        stderr=proc.stderr[:OUTPUT_LIMIT],
    )
