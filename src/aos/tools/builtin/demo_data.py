import csv
import threading

from sqlalchemy import Engine, text

from aos.config import get_settings
from aos.db.session import get_engine

COLUMNS = {
    "database": "TEXT PRIMARY KEY",
    "dataset": "TEXT",
    "vectors_millions": "REAL",
    "recall_at_10": "REAL",
    "p95_latency_ms": "REAL",
    "qps": "INTEGER",
    "index_build_minutes": "REAL",
    "monthly_cost_usd": "REAL",
    "license": "TEXT",
    "source": "TEXT",
}
NUMERIC = {
    "vectors_millions",
    "recall_at_10",
    "p95_latency_ms",
    "index_build_minutes",
    "monthly_cost_usd",
}

_lock = threading.Lock()
_seeded: set[int] = set()


def demo_table(engine: Engine) -> str:
    return "benchmarks" if engine.dialect.name == "sqlite" else "demo.benchmarks"


def ensure_demo_data() -> None:
    engine = get_engine()
    with _lock:
        if id(engine) in _seeded:
            return
        table = demo_table(engine)
        rows = _load_rows()
        with engine.begin() as conn:
            if engine.dialect.name != "sqlite":
                conn.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS demo")
            columns = ", ".join(f"{name} {kind}" for name, kind in COLUMNS.items())
            conn.exec_driver_sql(f"CREATE TABLE IF NOT EXISTS {table} ({columns})")
            if not conn.exec_driver_sql(f"SELECT COUNT(*) FROM {table}").scalar():
                names = ", ".join(COLUMNS)
                params = ", ".join(f":{name}" for name in COLUMNS)
                conn.execute(text(f"INSERT INTO {table} ({names}) VALUES ({params})"), rows)
        _seeded.add(id(engine))


def reset_demo_data() -> None:
    engine = get_engine()
    with _lock, engine.begin() as conn:
        conn.exec_driver_sql(f"DROP TABLE IF EXISTS {demo_table(engine)}")
        _seeded.discard(id(engine))


def _load_rows() -> list[dict]:
    path = get_settings().fixtures_dir / "demo" / "benchmarks.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        for key in NUMERIC:
            row[key] = float(row[key])
        row["qps"] = int(row["qps"])
    return rows
