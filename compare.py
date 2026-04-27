"""Compare engine: relative change, exceedance fraction, and percentiles
between paired baseline (untreated) and scenario (treated) xPollinator runs.

Replicate pairing: when a baseline and scenario run share their RandomSeed
(as the run_batch.py manifest enforces), replicate index i in both runs uses
the same BEEHAVE seed, so pairing by index yields a paired-difference design.
If replicate counts differ, the shorter is used.
"""
from __future__ import annotations

import logging
import pickle

import numpy as np
from sqlalchemy.orm import Session

from models import BeePopulationReplicate, Run

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLD = 0.10
DEFAULT_PERCENTILES = (10, 50, 90)


def _load_run_matrix(session: Session, run_id: int, metric: str) -> np.ndarray | None:
    """(n_replicates, n_days) float32 matrix for one run + metric, ordered by replicate_idx."""
    rows = (
        session.query(BeePopulationReplicate)
        .filter_by(run_id=run_id, metric_name=metric)
        .order_by(BeePopulationReplicate.replicate_idx)
        .all()
    )
    if not rows:
        return None
    return np.vstack([pickle.loads(r.timeseries) for r in rows]).astype(np.float32)


def compute_relative(
    session: Session, baseline_id: int, scenario_id: int, metric: str
) -> np.ndarray | None:
    """(n_pairs, n_days) relative change (scenario - baseline) / baseline.

    Days where baseline == 0 produce NaN to avoid divide-by-zero.
    """
    baseline = _load_run_matrix(session, baseline_id, metric)
    scenario = _load_run_matrix(session, scenario_id, metric)
    if baseline is None or scenario is None:
        return None
    n_pairs = min(baseline.shape[0], scenario.shape[0])
    n_days = min(baseline.shape[1], scenario.shape[1])
    b = baseline[:n_pairs, :n_days]
    s = scenario[:n_pairs, :n_days]
    with np.errstate(divide="ignore", invalid="ignore"):
        rel = np.where(b == 0, np.nan, (s - b) / b)
    return rel.astype(np.float32)


def compute_exceedance(rel: np.ndarray, threshold: float = DEFAULT_THRESHOLD) -> np.ndarray:
    """Per-day fraction of replicate pairs with |rel| > threshold (NaN-safe)."""
    abs_rel = np.abs(rel)
    valid = ~np.isnan(abs_rel)
    exceeded = (abs_rel > threshold) & valid
    n_valid = valid.sum(axis=0).astype(np.float32)
    n_exceeded = exceeded.sum(axis=0).astype(np.float32)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(n_valid > 0, n_exceeded / n_valid, 0.0).astype(np.float32)


def compute_percentiles_relative(
    rel: np.ndarray, percentiles=DEFAULT_PERCENTILES
) -> dict[str, list[float]]:
    """Day-wise percentiles of the relative change across replicate pairs."""
    return {f"p{p}": np.nanpercentile(rel, p, axis=0).tolist() for p in percentiles}


def compute_percentiles_pairs(
    session: Session,
    baseline_ids: list[int],
    scenario_ids: list[int],
    metric: str,
    threshold: float = DEFAULT_THRESHOLD,
    percentiles=DEFAULT_PERCENTILES,
) -> dict:
    """Spatial percentiles (across hives, per day) and temporal percentiles
    (across days, per hive) of the per-(hive, day) exceedance fraction.

    baseline_ids and scenario_ids are parallel — index i represents one hive's pair.
    """
    if len(baseline_ids) != len(scenario_ids):
        raise ValueError("baseline_ids and scenario_ids must have equal length")
    per_hive: list[np.ndarray] = []
    hive_meta: list[dict] = []
    for baseline_id, scenario_id in zip(baseline_ids, scenario_ids):
        rel = compute_relative(session, baseline_id, scenario_id, metric)
        if rel is None:
            logger.warning(
                f"Skipping pair ({baseline_id}, {scenario_id}): no data for metric '{metric}'"
            )
            continue
        per_hive.append(compute_exceedance(rel, threshold))
        baseline_run = session.query(Run).filter_by(id=baseline_id).first()
        hive_meta.append(
            {
                "baseline_id": baseline_id,
                "scenario_id": scenario_id,
                "hive_group_id": baseline_run.hive_group_id if baseline_run else None,
            }
        )
    if not per_hive:
        return {"spatial": {"per_day": {}}, "temporal": {"per_hive": []}}
    matrix = np.vstack(per_hive)  # (n_hives, n_days)
    spatial = {f"p{p}": np.percentile(matrix, p, axis=0).tolist() for p in percentiles}
    temporal_per_hive = []
    for i, exc in enumerate(per_hive):
        entry = dict(hive_meta[i])
        entry.update({f"p{p}": float(np.percentile(exc, p)) for p in percentiles})
        temporal_per_hive.append(entry)
    return {
        "spatial": {"per_day": spatial},
        "temporal": {"per_hive": temporal_per_hive},
    }
