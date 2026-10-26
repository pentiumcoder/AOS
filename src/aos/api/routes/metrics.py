from typing import Any

from fastapi import APIRouter, HTTPException, Query

from aos.observability import metrics
from aos.observability.costs import run_metrics

router = APIRouter(tags=["metrics"])


@router.get("/runs/{run_id}/metrics")
def get_run_metrics(run_id: str) -> dict[str, Any]:
    try:
        return run_metrics(run_id)
    except KeyError as exc:
        raise HTTPException(404, "run not found") from exc


@router.get("/metrics/summary")
def get_summary(days: int = Query(default=7, ge=1, le=365)) -> dict[str, Any]:
    return metrics.summary(days)
