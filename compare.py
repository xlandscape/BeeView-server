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
DEFAULT_PERCENTILES = tuple(range(10, 100, 10))  # p10, p20, ... , p90


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


def compute_exceedance(
    rel: np.ndarray,
    threshold: float = DEFAULT_THRESHOLD,
    mode: str = "decline",
) -> np.ndarray:
    """Per-day fraction of replicate pairs that exceed a threshold (NaN-safe).

    Modes:
      - decline: rel <= -threshold (one-sided decline relative to baseline)
      - absolute: |rel| > threshold (two-sided absolute change)
    """
    valid = ~np.isnan(rel)
    if mode == "absolute":
        exceeded = (np.abs(rel) > threshold) & valid
    else:
        exceeded = (rel <= -threshold) & valid
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
    mode: str = "decline",
    percentiles=DEFAULT_PERCENTILES,
    spatial_scope: str = "pair",
) -> dict:
    """Spatial percentiles (across hives, per day) and temporal percentiles
    (across days, per hive) of the per-(hive, day) exceedance fraction.

    baseline_ids and scenario_ids are parallel — index i represents one hive's pair.
    """
    if len(baseline_ids) != len(scenario_ids):
        raise ValueError("baseline_ids and scenario_ids must have equal length")
    per_pair: list[np.ndarray] = []
    pair_meta: list[dict] = []
    for baseline_id, scenario_id in zip(baseline_ids, scenario_ids):
        rel = compute_relative(session, baseline_id, scenario_id, metric)
        if rel is None:
            logger.warning(
                f"Skipping pair ({baseline_id}, {scenario_id}): no data for metric '{metric}'"
            )
            continue
        per_pair.append(compute_exceedance(rel, threshold, mode))
        baseline_run = session.query(Run).filter_by(id=baseline_id).first()
        scenario_run = session.query(Run).filter_by(id=scenario_id).first()
        pair_meta.append(
            {
                "baseline_id": baseline_id,
                "scenario_id": scenario_id,
                "hive_group_id": baseline_run.hive_group_id if baseline_run else None,
                "batch_sim_id": getattr(baseline_run, "batch_sim_id", None) if baseline_run else None,
                "outer_mc_id": getattr(baseline_run, "outer_mc_id", None) if baseline_run else None,
                "baseline_sim_id": baseline_run.sim_id if baseline_run else None,
                "scenario_sim_id": scenario_run.sim_id if scenario_run else None,
            }
        )
    if not per_pair:
        return {"days": [], "spatial": {"per_day": {}}, "temporal": {"per_hive": []}, "per_hive_daily": []}

    if spatial_scope not in {"pair", "hive_mean"}:
        raise ValueError("spatial_scope must be 'pair' or 'hive_mean'")

    # pair: each selected treated/untreated pair contributes one spatial sample.
    # hive_mean: collapse multiple MC pairs for the same hive by averaging exceedance per day.
    if spatial_scope == "hive_mean":
        grouped: dict[str, list[np.ndarray]] = {}
        grouped_meta: dict[str, dict] = {}
        for meta, exc in zip(pair_meta, per_pair):
            key = str(meta.get("hive_group_id") or meta.get("baseline_id"))
            grouped.setdefault(key, []).append(exc)
            if key not in grouped_meta:
                grouped_meta[key] = {
                    "hive_group_id": meta.get("hive_group_id"),
                    "n_mc_pairs": 0,
                    "baseline_ids": [],
                    "scenario_ids": [],
                }
            grouped_meta[key]["n_mc_pairs"] += 1
            grouped_meta[key]["baseline_ids"].append(meta.get("baseline_id"))
            grouped_meta[key]["scenario_ids"].append(meta.get("scenario_id"))

        per_spatial = []
        spatial_meta = []
        for key in sorted(grouped.keys()):
            arrs = grouped[key]
            per_spatial.append(np.nanmean(np.vstack(arrs), axis=0).astype(np.float32))
            spatial_meta.append(grouped_meta[key])
    else:
        per_spatial = per_pair
        spatial_meta = pair_meta

    matrix = np.vstack(per_spatial)  # (n_spatial_units, n_days)
    n_days = matrix.shape[1]
    days = list(range(1, n_days + 1))
    spatial = {f"p{p}": np.nanpercentile(matrix, p, axis=0).tolist() for p in percentiles}
    temporal_per_hive = []
    per_hive_daily = []
    for i, exc in enumerate(per_spatial):
        entry = dict(spatial_meta[i])
        entry.update({f"p{p}": float(np.nanpercentile(exc, p)) for p in percentiles})
        temporal_per_hive.append(entry)
        daily_entry = dict(spatial_meta[i])
        daily_entry["exceedance"] = exc.tolist()
        per_hive_daily.append(daily_entry)
    return {
        "days": days,
        "spatial": {"per_day": spatial},
        "temporal": {"per_hive": temporal_per_hive},
        "per_hive_daily": per_hive_daily,
        "spatial_scope": spatial_scope,
        "n_spatial_units": int(len(per_spatial)),
        "n_selected_pairs": int(len(per_pair)),
    }


# ─── Reduction percentile matrix ─────────────────────────────────────────────


def compute_reduction_matrix(
    session: Session,
    baseline_ids: list[int],
    scenario_ids: list[int],
    metric: str,
    percentiles=DEFAULT_PERCENTILES,
    spatial_scope: str = "pair",
) -> dict:
    """Percent-reduction percentile matrix (spatial × temporal).

    Each cell (pS, pT) = pS-th spatial percentile across locations of the
    pT-th temporal percentile across days of the mean percent-reduction.

    Reduction = (baseline - scenario) / baseline.  Positive → decline.
    Days where baseline == 0 contribute 0 (no reduction when both are zero).
    """
    if len(baseline_ids) != len(scenario_ids):
        raise ValueError("baseline_ids and scenario_ids must have equal length")

    per_unit_daily: list[np.ndarray] = []  # each (n_days,)
    unit_meta: list[dict] = []

    for baseline_id, scenario_id in zip(baseline_ids, scenario_ids):
        baseline = _load_run_matrix(session, baseline_id, metric)
        scenario = _load_run_matrix(session, scenario_id, metric)
        if baseline is None or scenario is None:
            logger.warning(
                "Skipping pair (%s, %s): no data for metric '%s'",
                baseline_id, scenario_id, metric,
            )
            continue
        n_pairs = min(baseline.shape[0], scenario.shape[0])
        n_days = min(baseline.shape[1], scenario.shape[1])
        b = baseline[:n_pairs, :n_days]
        s = scenario[:n_pairs, :n_days]

        with np.errstate(divide="ignore", invalid="ignore"):
            reduction = np.where(b == 0, 0.0, (b - s) / b)
        daily_mean = np.nanmean(reduction, axis=0).astype(np.float32)

        per_unit_daily.append(daily_mean)
        run = session.query(Run).filter_by(id=baseline_id).first()
        unit_meta.append({
            "baseline_id": baseline_id,
            "scenario_id": scenario_id,
            "hive_group_id": run.hive_group_id if run else None,
        })

    if not per_unit_daily:
        return {
            "matrix": [],
            "spatial_percentiles": list(percentiles),
            "temporal_percentiles": list(percentiles),
            "n_days": 0,
            "n_spatial_units": 0,
            "n_selected_pairs": 0,
            "metric": metric,
            "spatial_scope": spatial_scope,
        }

    # Optional hive-mean grouping: average MC pairs sharing the same hive.
    if spatial_scope == "hive_mean":
        grouped: dict[str, list[np.ndarray]] = {}
        for meta, daily in zip(unit_meta, per_unit_daily):
            key = str(meta.get("hive_group_id") or meta["baseline_id"])
            grouped.setdefault(key, []).append(daily)
        spatial_units = [
            np.nanmean(np.vstack(arrs), axis=0).astype(np.float32)
            for arrs in (grouped[k] for k in sorted(grouped))
        ]
    else:
        spatial_units = per_unit_daily

    n_days = int(spatial_units[0].shape[0])
    n_units = len(spatial_units)
    pcts = list(percentiles)

    # Temporal percentiles per spatial unit → (n_units, n_pcts)
    temporal_matrix = np.zeros((n_units, len(pcts)), dtype=np.float32)
    for i, daily in enumerate(spatial_units):
        for j, p in enumerate(pcts):
            temporal_matrix[i, j] = np.nanpercentile(daily, p)

    # Spatial percentiles across units → (n_spatial_pcts, n_temporal_pcts)
    result = np.zeros((len(pcts), len(pcts)), dtype=np.float32)
    for t_idx in range(len(pcts)):
        col = temporal_matrix[:, t_idx]
        for s_idx, sp in enumerate(pcts):
            result[s_idx, t_idx] = float(np.nanpercentile(col, sp))

    # Convert to percent for convenience (0.10 → 10.0).
    return {
        "matrix": (result * 100).tolist(),
        "spatial_percentiles": pcts,
        "temporal_percentiles": pcts,
        "n_days": n_days,
        "n_spatial_units": n_units,
        "n_selected_pairs": len(per_unit_daily),
        "metric": metric,
        "spatial_scope": spatial_scope,
    }


# ─── Effect-Days (ED) matrix ─────────────────────────────────────────────────

ED_PERCENTILES = tuple(range(10, 101, 10))  # p10, p20, ..., p100


def compute_ed_matrix(
    session: Session,
    baseline_ids: list[int],
    scenario_ids: list[int],
    metric: str,
    threshold: float = DEFAULT_THRESHOLD,
) -> dict:
    """Compute the Effect-Days percentile matrix (temporal × spatial).

    For each replicate r at location h:
        ED(r, h) = number of days where scenario(r,h,d) < baseline(r,h,d) * (1 - threshold)

    Construction (temporal first, then spatial):
        1. For each location h: tp(h, pct) = percentile of {ED(r, h)} across replicates
           → shape (n_hives, 10)
        2. For each temporal percentile rank pct: sp(pct, q) = percentile of {tp(h, pct)} across h
           → shape (10, 10) matrix

    Returns dict with 'matrix' (10×10 list-of-lists), row/col labels, metadata.
    """
    if len(baseline_ids) != len(scenario_ids):
        raise ValueError("baseline_ids and scenario_ids must have equal length")

    # Collect ED arrays per hive: each entry is shape (n_replicates,)
    ed_per_hive: list[np.ndarray] = []
    hive_labels: list[str] = []
    n_days_used = 0

    for baseline_id, scenario_id in zip(baseline_ids, scenario_ids):
        baseline = _load_run_matrix(session, baseline_id, metric)
        scenario = _load_run_matrix(session, scenario_id, metric)
        if baseline is None or scenario is None:
            logger.warning(
                f"Skipping pair ({baseline_id}, {scenario_id}): no data for metric '{metric}'"
            )
            continue
        n_pairs = min(baseline.shape[0], scenario.shape[0])
        n_days = min(baseline.shape[1], scenario.shape[1])
        n_days_used = max(n_days_used, n_days)
        b = baseline[:n_pairs, :n_days]
        s = scenario[:n_pairs, :n_days]
        # ED per replicate: count days where scenario < baseline * (1 - threshold)
        effect_indicator = s < b * (1.0 - threshold)
        ed = effect_indicator.sum(axis=1).astype(np.float32)  # shape (n_pairs,)
        ed_per_hive.append(ed)
        run = session.query(Run).filter_by(id=baseline_id).first()
        hive_labels.append(run.hive_group_id if run else str(baseline_id))

    if not ed_per_hive:
        return {
            "matrix": [],
            "temporal_percentiles": [],
            "spatial_percentiles": [],
            "n_days": 0,
            "n_hives": 0,
            "n_replicates": 0,
            "threshold": threshold,
            "metric": metric,
            "hive_labels": [],
        }

    n_hives = len(ed_per_hive)
    n_replicates = min(len(ed) for ed in ed_per_hive)
    percentiles = list(ED_PERCENTILES)

    # Step 1: temporal percentiles — for each hive, percentiles across replicates
    # tp_matrix shape: (n_hives, 10)
    tp_matrix = np.zeros((n_hives, len(percentiles)), dtype=np.float32)
    for h_idx, ed in enumerate(ed_per_hive):
        for p_idx, pct in enumerate(percentiles):
            tp_matrix[h_idx, p_idx] = np.percentile(ed, pct)

    # Step 2: spatial percentiles — for each temporal rank, percentiles across hives
    # result_matrix shape: (10 temporal, 10 spatial)
    result_matrix = np.zeros((len(percentiles), len(percentiles)), dtype=np.float32)
    for tp_idx in range(len(percentiles)):
        tp_values = tp_matrix[:, tp_idx]  # one value per hive
        for sp_idx, sp_pct in enumerate(percentiles):
            result_matrix[tp_idx, sp_idx] = np.percentile(tp_values, sp_pct)

    return {
        "matrix": result_matrix.tolist(),
        "temporal_percentiles": percentiles,
        "spatial_percentiles": percentiles,
        "n_days": int(n_days_used),
        "n_hives": n_hives,
        "n_replicates": n_replicates,
        "threshold": threshold,
        "metric": metric,
        "hive_labels": hive_labels,
    }


# ─── Overwintering survival probability ──────────────────────────────────────

SURVIVAL_METRIC = "TotalIHbees + TotalForagers"
SURVIVAL_THRESHOLD = 4000


def compute_survival_probabilities(
    session: Session,
    baseline_ids: list[int],
    scenario_ids: list[int],
    metric: str = SURVIVAL_METRIC,
    threshold: int = SURVIVAL_THRESHOLD,
) -> dict:
    """Compute overwintering survival probability for paired runs.

    For each run, survival = fraction of replicates where the metric value on
    the last simulation day >= threshold.

    Returns per-hive survival probabilities and the absolute effect
    (baseline - scenario; positive means treatment reduces survival).
    """
    if len(baseline_ids) != len(scenario_ids):
        raise ValueError("baseline_ids and scenario_ids must have equal length")

    hives: list[dict] = []

    for baseline_id, scenario_id in zip(baseline_ids, scenario_ids):
        baseline = _load_run_matrix(session, baseline_id, metric)
        scenario = _load_run_matrix(session, scenario_id, metric)

        if baseline is None or scenario is None:
            logger.warning(
                f"Skipping pair ({baseline_id}, {scenario_id}): no data for metric '{metric}'"
            )
            continue

        # Last day value for each replicate (index -1 = final simulation timestep)
        baseline_last = baseline[:, -1]
        scenario_last = scenario[:, -1]

        n_baseline = len(baseline_last)
        n_scenario = len(scenario_last)

        baseline_survival = float(np.sum(baseline_last >= threshold) / n_baseline)
        scenario_survival = float(np.sum(scenario_last >= threshold) / n_scenario)
        effect = baseline_survival - scenario_survival

        run = session.query(Run).filter_by(id=baseline_id).first()
        hives.append({
            "hive_group_id": run.hive_group_id if run else str(baseline_id),
            "baseline_id": baseline_id,
            "scenario_id": scenario_id,
            "baseline_survival": round(baseline_survival, 4),
            "scenario_survival": round(scenario_survival, 4),
            "effect": round(effect, 4),
            "n_replicates_baseline": n_baseline,
            "n_replicates_scenario": n_scenario,
        })

    return {
        "hives": hives,
        "threshold": threshold,
        "metric": metric,
    }
