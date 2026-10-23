from pathlib import Path

from pydantic import BaseModel, Field

from aos.tools.base import ToolContext, ToolError


class FileReadInput(BaseModel):
    path: str = Field(min_length=1)
    max_chars: int = Field(default=20_000, ge=1, le=200_000)


class FileWriteInput(BaseModel):
    path: str = Field(min_length=1)
    content: str
    append: bool = False


class FileDeleteInput(BaseModel):
    path: str = Field(min_length=1)


def resolve_in_workspace(ctx: ToolContext, path: str) -> Path:
    root = ctx.workspace.resolve()
    target = (root / path).resolve()
    if target != root and root not in target.parents:
        raise ToolError(f"path escapes the workspace: {path}")
    return target


def file_read(args: FileReadInput, ctx: ToolContext) -> dict:
    target = resolve_in_workspace(ctx, args.path)
    if not target.is_file():
        raise ToolError(f"no such file: {args.path}")
    text = target.read_text(encoding="utf-8", errors="replace")
    return {
        "path": args.path,
        "size": len(text),
        "content": text[: args.max_chars],
        "truncated": len(text) > args.max_chars,
    }


def file_write(args: FileWriteInput, ctx: ToolContext) -> dict:
    target = resolve_in_workspace(ctx, args.path)
    if target.is_dir():
        raise ToolError(f"{args.path} is a directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a" if args.append else "w", encoding="utf-8") as handle:
        handle.write(args.content)
    return {"path": args.path, "bytes": len(args.content.encode("utf-8")), "append": args.append}


def file_delete(args: FileDeleteInput, ctx: ToolContext) -> dict:
    target = resolve_in_workspace(ctx, args.path)
    if not target.is_file():
        raise ToolError(f"no such file: {args.path}")
    target.unlink()
    return {"path": args.path, "deleted": True}
