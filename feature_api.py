"""Per-feature endpoints used by the BeeView parcel popup.

Kept in its own router so main.py only needs one include_router line.
"""

from typing import Optional
from fastapi import APIRouter, HTTPException, Query

from database import get_session
from models import Application

router = APIRouter(prefix="/api/features", tags=["features"])


def _parse_run_ids(run_ids: Optional[str]) -> list[int]:
    if not run_ids:
        return []
    try:
        return sorted({int(part) for part in run_ids.split(",") if part.strip()})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="run_ids must be a comma-separated list of integers") from exc


@router.get("/{feature_id}/applications")
def get_feature_applications(
    feature_id: int,
    run_ids: Optional[str] = Query(default=None, description="Comma-separated run ids; omit for all runs"),
):
    """Application events of one landscape feature across the given runs.

    Reads the ``applications`` table only (runs imported with import_run.py);
    legacy file-based runs without table rows yield an empty list.
    Returns ``[{run_id, application_day, conc_nectar, conc_pollen, contact}]``
    ordered by run id, then application day.
    """
    ids = _parse_run_ids(run_ids)
    session = next(get_session())
    try:
        query = session.query(Application).filter(Application.lulc_feature_id == feature_id)
        if ids:
            query = query.filter(Application.run_id.in_(ids))
        rows = query.order_by(Application.run_id, Application.application_day).all()
        return [
            {
                "run_id": r.run_id,
                "application_day": r.application_day,
                "conc_nectar": r.conc_nectar,
                "conc_pollen": r.conc_pollen,
                "contact": r.contact,
            }
            for r in rows
        ]
    finally:
        session.close()
