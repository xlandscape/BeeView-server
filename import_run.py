"""Import an xPollinator run folder into the BeeView database.

Usage:
    python import_run.py <path/to/run/SimID> [--force]

Reads:
  - <folder>/user.xml              - parameter file (the original .xrun content)
  - <folder>/mcs/X3*/processing/BeeHave/output.csv - BEEHAVE BehaviorSpace output

Writes:
  - one row in runs with the run's metadata (hive location transformed to WGS84)
  - N_replicates * N_metrics rows in bee_population_replicate, keyed by run_id

Pass --force to replace an existing run with the same SimID.
"""
import argparse
import glob
import logging
import os
import pickle
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text

from database import Base, engine, get_session
from models import BeePopulationReplicate, Run
from xml_parser import transform_coordinates_to_wgs84

logger = logging.getLogger("import_run")


def _relative_source_path(folder: Path) -> Path:
    """Return *folder* as a path relative to CWD when possible (portability)."""
    try:
        return folder.resolve().relative_to(Path.cwd())
    except ValueError:
        return folder.resolve()


# Canonical metrics used by compare UI and charts.
CANONICAL_METRIC_COLUMNS = [
    "TotalIHbees + TotalForagers + TotalDroneEggs + TotalEggs + TotalDroneLarvae + TotalLarvae + TotalDronePupae + TotalPupae",
    "TotalIHbees + TotalForagers",
    "TotalDroneEggs + TotalEggs",
    "TotalDroneLarvae + TotalLarvae",
    "TotalDronePupae + TotalPupae",
    "HoneyEnergyStore",
    "PollenStore_g",
]

# Raw metrics in newer BEEHAVE output.csv format.
RAW_METRIC_COLUMNS = [
    "TotalIHbees",
    "TotalForagers",
    "TotalDroneEggs",
    "TotalEggs",
    "TotalDroneLarvae",
    "TotalLarvae",
    "TotalDronePupae",
    "TotalPupae",
]

DERIVED_METRIC_FORMULAS = {
    "TotalIHbees + TotalForagers + TotalDroneEggs + TotalEggs + TotalDroneLarvae + TotalLarvae + TotalDronePupae + TotalPupae": [
        "TotalIHbees",
        "TotalForagers",
        "TotalDroneEggs",
        "TotalEggs",
        "TotalDroneLarvae",
        "TotalLarvae",
        "TotalDronePupae",
        "TotalPupae",
    ],
    "TotalIHbees + TotalForagers": ["TotalIHbees", "TotalForagers"],
    "TotalDroneEggs + TotalEggs": ["TotalDroneEggs", "TotalEggs"],
    "TotalDroneLarvae + TotalLarvae": ["TotalDroneLarvae", "TotalLarvae"],
    "TotalDronePupae + TotalPupae": ["TotalDronePupae", "TotalPupae"],
}

STORED_METRIC_COLUMNS = list(dict.fromkeys(CANONICAL_METRIC_COLUMNS + RAW_METRIC_COLUMNS))


def ensure_runs_schema(session) -> None:
    """Add Phase 2 Run columns when importing into an existing DuckDB database."""
    try:
        rows = session.execute(text("PRAGMA table_info('runs')")).fetchall()
    except Exception:
        # Table might not exist yet; create_all will handle it.
        return

    existing_columns = {row[1] for row in rows}
    missing_ddl = []
    if "batch_sim_id" not in existing_columns:
        missing_ddl.append("ALTER TABLE runs ADD COLUMN batch_sim_id VARCHAR")
    if "outer_mc_id" not in existing_columns:
        missing_ddl.append("ALTER TABLE runs ADD COLUMN outer_mc_id INTEGER")
    if "mc_folder_name" not in existing_columns:
        missing_ddl.append("ALTER TABLE runs ADD COLUMN mc_folder_name VARCHAR")

    for ddl in missing_ddl:
        session.execute(text(ddl))
    if missing_ddl:
        session.commit()


def _text(root: ET.Element, tag: str, default: str | None = None) -> str | None:
    el = root.find(tag)
    if el is None or el.text is None:
        return default
    return el.text.strip()


def parse_user_xml(user_xml_path: Path) -> dict:
    """Parse user.xml (the .xrun copy) into a metadata dict."""
    tree = ET.parse(user_xml_path)
    root = tree.getroot()
    min_apps = int(_text(root, "MinNumberApplications", "0") or 0)
    max_apps = int(_text(root, "MaxNumberApplications", "0") or 0)
    return {
        "sim_id": _text(root, "SimID"),
        "label": _text(root, "RunLabel"),
        "scenario": _text(root, "Project"),
        "hive_group_id": _text(root, "HiveGroupId"),
        "hive_x": float(_text(root, "BeeHaveMapCenterPointX", "0") or 0),
        "hive_y": float(_text(root, "BeeHaveMapCenterPointY", "0") or 0),
        "n_replicates": int(_text(root, "NumberBeeHaveReplicates", "1") or 1),
        "random_seed": int(_text(root, "BeeHaveRandomSeed", "0") or 0),
        "treatment_on": max_apps > 0,
        "sim_start": _text(root, "SimulationStart"),
    }


def find_all_mc_folders(run_folder: Path) -> list[Path]:
    """Locate all BEEHAVE output.csv files under MC folders (X3*).
    
    Returns a list of MC folder paths, sorted alphabetically for deterministic ordering.
    """
    mcs_dir = run_folder / "mcs"
    if not mcs_dir.exists():
        raise FileNotFoundError(f"No mcs/ directory found in {run_folder}")
    
    mc_folders = sorted([d for d in mcs_dir.iterdir() if d.is_dir() and d.name.startswith("X3")])
    if not mc_folders:
        raise FileNotFoundError(f"No X3* MC folders found under {mcs_dir}")
    
    result = []
    for mc_folder in mc_folders:
        output_csv = mc_folder / "processing" / "BeeHave" / "output.csv"
        if output_csv.exists():
            result.append(mc_folder)
    
    if not result:
        raise FileNotFoundError(f"No output.csv found in any X3* MC folder under {mcs_dir}")
    
    return result


def _normalize(name: str) -> str:
    """Collapse whitespace so NetLogo's XML-indented metric names match our expected names."""
    return " ".join(name.split())


def _extract_metric_array(group_sorted: pd.DataFrame, metric_name: str) -> np.ndarray | None:
    """Return one metric's timeseries as float64 array from direct or derived columns."""
    normalized_to_actual = {_normalize(col): col for col in group_sorted.columns}
    metric_normalized = _normalize(metric_name)

    # Legacy format: metric expression appears directly as a CSV column.
    direct_col = normalized_to_actual.get(metric_normalized)
    if direct_col:
        return group_sorted[direct_col].to_numpy(dtype=np.float64)

    # New format: derive canonical metrics from primitive columns.
    formula = DERIVED_METRIC_FORMULAS.get(metric_name)
    if not formula:
        return None

    missing = [name for name in formula if _normalize(name) not in normalized_to_actual]
    if missing:
        return None

    arrays = [
        group_sorted[normalized_to_actual[_normalize(name)]].to_numpy(dtype=np.float64)
        for name in formula
    ]
    return np.sum(np.vstack(arrays), axis=0)


def parse_bee_population_replicates(csv_path: Path) -> dict[tuple[int, str], np.ndarray]:
    """Return {(replicate_idx, metric_name): float32[n_steps]} from a BehaviorSpace CSV.

    BEEHAVE BehaviorSpace CSVs have 6 metadata rows followed by the column header (row 7),
    then data rows. With steppedValueSet on RAND_SEED, each seed becomes a distinct
    [run number] value. Rows per (run, step) are already sorted ascending. Column names
    inherit the exact whitespace from experiment.xml's <metric> element, including
    newlines/indentation, so we match on a normalized form.
    """
    df = pd.read_csv(csv_path, skiprows=6)
    df.columns = [_normalize(c) for c in df.columns]
    if "[run number]" not in df.columns or "[step]" not in df.columns:
        raise ValueError(f"CSV missing [run number] or [step] columns: {csv_path}")
    result: dict[tuple[int, str], np.ndarray] = {}
    for run_number, group in df.groupby("[run number]"):
        group_sorted = group.sort_values("[step]")
        for metric_name in STORED_METRIC_COLUMNS:
            arr = _extract_metric_array(group_sorted, metric_name)
            if arr is None:
                # Keep warnings for canonical metrics to make ingest issues visible.
                if metric_name in CANONICAL_METRIC_COLUMNS:
                    logger.warning(f"Metric unavailable in CSV: {metric_name}")
                continue
            arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
            result[(int(run_number), metric_name)] = arr.astype(np.float32)
    return result


def import_run(run_folder: Path, force: bool = False) -> list[int]:
    """Import a run folder with all MC folders, return list of new Run.ids (one per MC).
    
    If multiple MC folders exist under mcs/, creates one Run record per MC with
    outer_mc_id set and sim_id suffixed with _MC<id>.
    """
    user_xml = run_folder / "user.xml"
    if not user_xml.exists():
        raise FileNotFoundError(f"user.xml not found in {run_folder}")
    meta = parse_user_xml(user_xml)
    if not meta["sim_id"]:
        raise ValueError(f"No <SimID> in {user_xml}")

    # Find all MC folders
    mc_folders = find_all_mc_folders(run_folder)
    logger.info(f"Found {len(mc_folders)} MC folder(s) for {meta['sim_id']}")

    wgs84 = transform_coordinates_to_wgs84(meta["hive_x"], meta["hive_y"])
    hive_lon, hive_lat = wgs84 if wgs84 else (None, None)

    Base.metadata.create_all(engine)
    session = next(get_session())
    try:
        ensure_runs_schema(session)

        # For --force: delete all runs with same batch_sim_id
        if force:
            existing_runs = session.query(Run).filter_by(batch_sim_id=meta["sim_id"]).all()
            if existing_runs:
                logger.info(f"--force: deleting {len(existing_runs)} existing run(s) with batch_sim_id={meta['sim_id']}")
                for run in existing_runs:
                    session.execute(
                        text("DELETE FROM bee_population_replicate WHERE run_id = :rid"),
                        {"rid": run.id},
                    )
                    session.commit()
                    session.execute(text("DELETE FROM runs WHERE id = :rid"), {"rid": run.id})
                    session.commit()

        imported_run_ids = []
        for outer_mc_id, mc_folder in enumerate(mc_folders):
            # Parse replicates from this MC's output.csv
            csv_path = mc_folder / "processing" / "BeeHave" / "output.csv"
            try:
                replicates = parse_bee_population_replicates(csv_path)
            except Exception as exc:
                logger.warning(
                    f"Skipping MC {outer_mc_id} ({mc_folder.name}): failed to parse {csv_path}: {exc}"
                )
                continue
            if not replicates:
                logger.warning(f"No replicate data in {csv_path}, skipping MC {outer_mc_id}")
                continue
            
            replicate_indices = sorted({idx for (idx, _) in replicates})
            n_replicates_actual = len(replicate_indices)
            if n_replicates_actual != meta["n_replicates"]:
                logger.warning(
                    f"MC {outer_mc_id} replicate count mismatch: user.xml says {meta['n_replicates']}, "
                    f"CSV has {n_replicates_actual}. Using CSV count."
                )

            # Generate unique sim_id for this MC
            mc_sim_id = f"{meta['sim_id']}_MC{outer_mc_id}"

            # Check if this specific MC already exists
            existing = session.query(Run).filter_by(sim_id=mc_sim_id).one_or_none()
            if existing and not force:
                raise RuntimeError(
                    f"Run '{mc_sim_id}' already imported (id={existing.id}); "
                    f"use --force to replace."
                )

            run = Run(
                sim_id=mc_sim_id,
                label=meta["label"],
                scenario=meta["scenario"],
                hive_group_id=meta["hive_group_id"] or meta["sim_id"].replace("_treated", ""),
                treatment_on=meta["treatment_on"],
                n_replicates=n_replicates_actual,
                random_seed=meta["random_seed"],
                hive_x=meta["hive_x"],
                hive_y=meta["hive_y"],
                hive_lon=hive_lon,
                hive_lat=hive_lat,
                source_path=str(_relative_source_path(run_folder)),
                sim_start=meta.get("sim_start"),
                batch_sim_id=meta["sim_id"],  # Parent SimID
                outer_mc_id=outer_mc_id,  # MC index
                mc_folder_name=mc_folder.name,  # e.g., "X3ER7MMTRUFYD2S5PB"
            )
            session.add(run)
            session.flush()

            for (replicate_idx, metric), arr in replicates.items():
                session.add(
                    BeePopulationReplicate(
                        run_id=run.id,
                        replicate_idx=replicate_idx,
                        metric_name=metric,
                        timeseries=pickle.dumps(arr),
                    )
                )
            session.commit()
            imported_run_ids.append(run.id)
            logger.info(
                f"Imported MC {outer_mc_id} for '{meta['sim_id']}' (run_id={run.id}): "
                f"{n_replicates_actual} replicates x {len(STORED_METRIC_COLUMNS)} configured metrics"
            )

        return imported_run_ids
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_folder", help="Path to xPollinator run folder, e.g. ../xPollinator/run/TestMultiRep")
    parser.add_argument("--force", action="store_true", help="Replace existing run with same SimID")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    folder = Path(args.run_folder).resolve()
    if not folder.is_dir():
        parser.error(f"Not a directory: {folder}")

    try:
        run_ids = import_run(folder, force=args.force)
        logger.info(f"Successfully imported {len(run_ids)} MC run(s): {run_ids}")
        return 0
    except Exception as exc:
        logger.error(f"Import failed: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
