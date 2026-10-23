import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from aos.db.session import get_engine
from aos.tools.base import ToolContext, ToolError
from aos.tools.builtin.demo_data import ensure_demo_data

FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|grant|revoke|truncate|copy|attach|detach|"
    r"pragma|vacuum|call|merge|replace|set|lock|listen|notify)\b",
    re.IGNORECASE,
)


class DbQueryInput(BaseModel):
    sql: str = Field(min_length=6, max_length=10_000, description="A single SELECT statement")
    max_rows: int = Field(default=200, ge=1, le=1000)


class DbQueryOutput(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    summary: dict[str, dict[str, Any]] = Field(
        default_factory=dict, description="Lowest and highest row for each numeric column"
    )


def db_query(args: DbQueryInput, ctx: ToolContext) -> DbQueryOutput:
    sql = args.sql.strip().rstrip(";").strip()
    if not re.match(r"(select|with)\b", sql, re.IGNORECASE):
        raise ToolError("only SELECT queries are allowed")
    if ";" in sql:
        raise ToolError("only one statement is allowed")
    if match := FORBIDDEN.search(sql):
        raise ToolError(f"keyword not allowed in a read-only query: {match.group(1).upper()}")

    ensure_demo_data()
    engine = get_engine()
    sqlite = engine.dialect.name == "sqlite"
    with engine.connect() as conn:
        if sqlite:
            conn.exec_driver_sql("PRAGMA query_only = ON")
        else:
            conn.exec_driver_sql("SET TRANSACTION READ ONLY")
            conn.exec_driver_sql("SET LOCAL search_path TO demo")
            conn.exec_driver_sql("SET LOCAL statement_timeout = 5000")
        try:
            # The raw DBAPI cursor keeps colons and percent signs in the query literal.
            cursor = conn.connection.cursor()
            cursor.execute(sql)
            columns = [d[0] for d in cursor.description or []]
            fetched = cursor.fetchmany(args.max_rows + 1)
        except Exception as exc:
            raise ToolError(f"query failed: {exc}") from exc
        finally:
            conn.rollback()
            if sqlite:
                conn.exec_driver_sql("PRAGMA query_only = OFF")
    rows = [[_jsonable(v) for v in row] for row in fetched[: args.max_rows]]
    return DbQueryOutput(
        columns=columns,
        rows=rows,
        row_count=len(rows),
        truncated=len(fetched) > args.max_rows,
        summary=summarize(columns, rows),
    )


def summarize(columns: list[str], rows: list[list[Any]]) -> dict[str, dict[str, Any]]:
    # Small models misread minimums and maximums from raw rows, so state them outright,
    # labelled with the row's name.
    if len(rows) < 2:
        return {}
    label = next(
        (i for i in range(len(columns)) if all(isinstance(row[i], str) for row in rows)), None
    )
    summary = {}
    for index, column in enumerate(columns):
        if not all(_is_number(row[index]) for row in rows):
            continue
        low = min(rows, key=lambda row: row[index])
        high = max(rows, key=lambda row: row[index])
        summary[column] = {
            "lowest": _extreme(low, index, label, columns),
            "highest": _extreme(high, index, label, columns),
        }
    return summary


def _extreme(row: list[Any], index: int, label: int | None, columns: list[str]) -> dict[str, Any]:
    entry: dict[str, Any] = {"value": row[index]}
    if label is not None:
        entry[columns[label]] = row[label]
    return entry


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value
