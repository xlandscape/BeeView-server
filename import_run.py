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

# Metric columns we extract from the BEEHAVE CSV. Order matches experiment.xml <metric> elements.
METRIC_COLUMNS = [
    "TotalIHbees + TotalForagers + TotalDroneEggs + TotalEggs + TotalDroneLarvae + TotalLarvae + TotalDronePupae + TotalPupae",
    "TotalIHbees + TotalForagers",
    "TotalDroneEggs + TotalEggs",
    "TotalDroneLarvae + TotalLarvae",
    "TotalDronePupae + TotalPupae",
    "HoneyEnergyStore",
    "PollenStore_g",
]


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
    }


def find_output_csv(run_folder: Path) -> Path:
    """Locate the BEEHAVE output.csv under the MC folder (typically X3*)."""
    pattern = str(run_folder / "mcs" / "X3*" / "processing" / "BeeHave" / "output.csv")
    matches = glob.glob(pattern)
    if not matches:
        raise FileNotFoundError(f"No BEEHAVE output.csv found under {run_folder}")
    if len(matches) > 1:
        logger.warning(f"Multiple output.csv found, using first: {matches[0]}")
    return Path(matches[0])


def _normalize(name: str) -> str:
    """Collapse whitespace so NetLogo's XML-indented metric names match our expected names."""
    return " ".join(name.split())


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
    expected = {_normalize(m): m for m in METRIC_COLUMNS}
    result: dict[tuple[int, str], np.ndarray] = {}
    for run_number, group in df.groupby("[run number]"):
        group_sorted = group.sort_values("[step]")
        for normalized, canonical in expected.items():
            if normalized not in group_sorted.columns:
                logger.warning(f"Metric column missing from CSV: {canonical}")
                continue
            arr = np.nan_to_num(group_sorted[normalized].to_numpy(dtype=np.float64), nan=0.0)
            result[(int(run_number), canonical)] = arr.astype(np.float32)
    return result


def import_run(run_folder: Path, force: bool = False) -> int:
    """Import a run folder, return the new Run.id."""
    user_xml = run_folder / "user.xml"
    if not user_xml.exists():
        raise FileNotFoundError(f"user.xml not found in {run_folder}")
    meta = parse_user_xml(user_xml)
    if not meta["sim_id"]:
        raise ValueError(f"No <SimID> in {user_xml}")

    csv_path = find_output_csv(run_folder)
    replicates = parse_bee_population_replicates(csv_path)
    if not replicates:
        raise ValueError(f"No replicate data parsed from {csv_path}")
    replicate_indices = sorted({idx for (idx, _) in replicates})
    n_replicates_actual = len(replicate_indices)
    if n_replicates_actual != meta["n_replicates"]:
        logger.warning(
            f"Replicate count mismatch: user.xml says {meta['n_replicates']}, "
            f"CSV has {n_replicates_actual}. Using CSV count."
        )

    wgs84 = transform_coordinates_to_wgs84(meta["hive_x"], meta["hive_y"])
    hive_lon, hive_lat = wgs84 if wgs84 else (None, None)

    Base.metadata.create_all(engine)
    session = next(get_session())
    try:
        existing = session.query(Run).filter_by(sim_id=meta["sim_id"]).one_or_none()
        if existing:
            if not force:
                raise RuntimeError(
                    f"Run '{meta['sim_id']}' already imported (id={existing.id}); "
                    f"use --force to replace."
                )
            existing_id = existing.id
            session.expunge(existing)
            # DuckDB enforces FKs synchronously; commit the child-table cleanup before the parent.
            session.execute(
                text("DELETE FROM bee_population_replicate WHERE run_id = :rid"),
                {"rid": existing_id},
            )
            session.commit()
            session.execute(text("DELETE FROM runs WHERE id = :rid"), {"rid": existing_id})
            session.commit()

        run = Run(
            sim_id=meta["sim_id"],
            label=meta["label"],
            scenario=meta["scenario"],
            hive_group_id=meta["hive_group_id"],
            treatment_on=meta["treatment_on"],
            n_replicates=n_replicates_actual,
            random_seed=meta["random_seed"],
            hive_x=meta["hive_x"],
            hive_y=meta["hive_y"],
            hive_lon=hive_lon,
            hive_lat=hive_lat,
            source_path=str(run_folder.resolve()),
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
        logger.info(
            f"Imported run '{run.sim_id}' (id={run.id}): "
            f"{n_replicates_actual} replicates x {len(METRIC_COLUMNS)} metrics"
        )
        return run.id
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
        import_run(folder, force=args.force)
        return 0
    except Exception as exc:
        logger.error(f"Import failed: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
