#!/usr/bin/env python3
"""Import all experiment folders from experiments/ into the BeeView database.

Scans for folders matching the pattern:
    exp{N}_TaG_hive{HH}_mc{MM}__{uuid}

Groups them by (hive, treatment) and imports each MC folder as a separate Run
with clean naming:
    sim_id:       hive{HH}_treated_MC{MM}  or  hive{HH}_MC{MM}
    batch_sim_id: hive{HH}_treated          or  hive{HH}
    hive_group_id: hive{HH}

exp1 = untreated, exp4 = treated.

Usage:
    python import_all_experiments.py [--force] [-v]
"""
import argparse
import logging
import pickle
import re
import sys
from pathlib import Path

import numpy as np
from sqlalchemy import text

from database import Base, engine, get_session
from import_run import (
    ensure_runs_schema,
    find_all_mc_folders,
    parse_bee_population_replicates,
    parse_user_xml,
    STORED_METRIC_COLUMNS,
)
from models import Application, BeePopulationReplicate, Run
from xml_parser import transform_coordinates_to_wgs84

logger = logging.getLogger("import_all_experiments")

EXPERIMENTS_DIR = Path("experiments")

# Map experiment prefix to treatment status
TREATMENT_MAP = {
    "exp1": False,
    "exp4": True,
}

FOLDER_PATTERN = re.compile(
    r"^(exp\d+)_(.+?)_hive(\d+)_mc(\d+)__(.+)$"
)


def scan_experiments(experiments_dir: Path) -> dict[tuple[str, str, bool], list[tuple[int, Path]]]:
    """Scan experiments dir and group folders by (hive_id, scenario, treated).

    Returns:
        {("36", "TaG", True): [(0, Path(...)), (1, Path(...)), ...], ...}
    """
    groups: dict[tuple[str, str, bool], list[tuple[int, Path]]] = {}

    for folder in sorted(experiments_dir.iterdir()):
        if not folder.is_dir():
            continue
        match = FOLDER_PATTERN.match(folder.name)
        if not match:
            logger.debug(f"Skipping non-matching folder: {folder.name}")
            continue

        exp_prefix = match.group(1)  # e.g. "exp1" or "exp4"
        scenario = match.group(2)     # e.g. "TaG"
        hive_id = match.group(3)      # e.g. "36"
        mc_num = int(match.group(4))  # e.g. 0

        if exp_prefix not in TREATMENT_MAP:
            logger.warning(f"Unknown experiment prefix '{exp_prefix}' in {folder.name}, skipping")
            continue

        treated = TREATMENT_MAP[exp_prefix]
        key = (hive_id, scenario, treated)
        groups.setdefault(key, []).append((mc_num, folder))

    # Sort each group by mc_num
    for key in groups:
        groups[key].sort(key=lambda x: x[0])

    return groups


def import_experiment_folder(
    mc_folder_path: Path,
    hive_id: str,
    treated: bool,
    mc_num: int,
    force: bool,
    session,
) -> int | None:
    """Import a single experiment folder as one Run.

    Returns the new Run.id, or None if skipped.
    """
    user_xml = mc_folder_path / "user.xml"
    if not user_xml.exists():
        logger.warning(f"No user.xml in {mc_folder_path.name}, skipping")
        return None

    meta = parse_user_xml(user_xml)

    # Build clean identifiers
    treatment_suffix = "_treated" if treated else ""
    batch_sim_id = f"hive{hive_id}{treatment_suffix}"
    sim_id = f"{batch_sim_id}_MC{mc_num}"

    # Find the single MC subfolder
    try:
        mc_subfolders = find_all_mc_folders(mc_folder_path)
    except FileNotFoundError as exc:
        logger.warning(f"Skipping {mc_folder_path.name}: {exc}")
        return None

    if len(mc_subfolders) != 1:
        logger.warning(
            f"Expected 1 MC subfolder in {mc_folder_path.name}, found {len(mc_subfolders)}"
        )

    mc_subfolder = mc_subfolders[0]

    # Parse bee population data
    csv_path = mc_subfolder / "processing" / "BeeHave" / "output.csv"
    try:
        replicates = parse_bee_population_replicates(csv_path)
    except Exception as exc:
        logger.warning(f"Skipping {mc_folder_path.name}: failed to parse output.csv: {exc}")
        return None

    if not replicates:
        logger.warning(f"No replicate data in {mc_folder_path.name}, skipping")
        return None

    replicate_indices = sorted({idx for (idx, _) in replicates})
    n_replicates = len(replicate_indices)

    # Check for existing run (match by sim_id OR by batch_sim_id + outer_mc_id)
    existing = session.query(Run).filter_by(sim_id=sim_id).one_or_none()
    if existing is None:
        existing = session.query(Run).filter_by(
            batch_sim_id=batch_sim_id, outer_mc_id=mc_num
        ).one_or_none()
    if existing:
        if not force:
            logger.info(f"Run '{sim_id}' already exists (id={existing.id}), skipping (use --force)")
            return None
        # Delete child rows first, then the run
        rid = existing.id
        session.execute(
            text("DELETE FROM bee_population_replicate WHERE run_id = :rid"),
            {"rid": rid},
        )
        session.execute(
            text("DELETE FROM applications WHERE run_id = :rid"),
            {"rid": rid},
        )
        session.commit()
        session.execute(text("DELETE FROM runs WHERE id = :rid"), {"rid": rid})
        session.commit()
        logger.info(f"Deleted existing run '{existing.sim_id}' (id={rid})")

    # Transform coordinates
    wgs84 = transform_coordinates_to_wgs84(meta["hive_x"], meta["hive_y"])
    hive_lon, hive_lat = wgs84 if wgs84 else (None, None)

    # Store path relative to CWD so the DB is portable across machines
    try:
        rel_source = str(mc_folder_path.resolve().relative_to(Path.cwd()))
    except ValueError:
        rel_source = str(mc_folder_path.resolve())

    run = Run(
        sim_id=sim_id,
        label=meta.get("label"),
        scenario=meta["scenario"],
        hive_group_id=f"hive{hive_id}",
        treatment_on=treated,
        n_replicates=n_replicates,
        random_seed=meta["random_seed"],
        hive_x=meta["hive_x"],
        hive_y=meta["hive_y"],
        hive_lon=hive_lon,
        hive_lat=hive_lat,
        source_path=rel_source,
        sim_start=meta.get("sim_start"),
        batch_sim_id=batch_sim_id,
        outer_mc_id=mc_num,
        mc_folder_name=mc_subfolder.name,
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

    # Store applications data if present (treated runs)
    _import_applications(session, run.id, mc_subfolder)

    session.commit()
    return run.id


def _import_applications(session, run_id: int, mc_subfolder: Path) -> int:
    """Parse applications.txt from the MC folder and store rows in the DB."""
    candidates = [
        mc_subfolder / "processing" / "BeeHave" / "applications.txt",
        mc_subfolder / "processing" / "BeeHaveEcotox" / "applications.txt",
        mc_subfolder / "BeeHaveEcotox" / "applications.txt",
    ]
    app_file = None
    for c in candidates:
        if c.is_file():
            app_file = c
            break
    if app_file is None:
        return 0

    count = 0
    with open(app_file, "r", encoding="utf-8") as f:
        for line in f.readlines()[1:]:  # skip header
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) < 5:
                continue
            try:
                session.add(Application(
                    run_id=run_id,
                    lulc_feature_id=int(parts[0]),
                    application_day=int(parts[1]),
                    conc_nectar=float(parts[2]),
                    conc_pollen=float(parts[3]),
                    contact=float(parts[4]),
                ))
                count += 1
            except (ValueError, IndexError):
                continue
    if count:
        logger.debug(f"Stored {count} application rows for run {run_id}")
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--force", action="store_true",
        help="Replace existing runs with same sim_id",
    )
    parser.add_argument(
        "--clean", action="store_true",
        help="Delete ALL existing runs before importing (fresh start)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument(
        "--experiments-dir", default=str(EXPERIMENTS_DIR),
        help=f"Path to experiments directory (default: {EXPERIMENTS_DIR})",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    experiments_dir = Path(args.experiments_dir)
    if not experiments_dir.is_dir():
        parser.error(f"Not a directory: {experiments_dir}")

    groups = scan_experiments(experiments_dir)
    if not groups:
        logger.error("No experiment folders found")
        return 1

    # Summary
    total_folders = sum(len(mcs) for mcs in groups.values())
    logger.info(f"Found {len(groups)} hive/treatment groups, {total_folders} total MC folders")
    for (hive_id, scenario, treated), mcs in sorted(groups.items()):
        label = f"hive{hive_id} {'treated' if treated else 'untreated'} ({scenario})"
        mc_nums = [mc_num for mc_num, _ in mcs]
        logger.info(f"  {label}: MCs {mc_nums}")

    # Import
    Base.metadata.create_all(engine)
    session = next(get_session())
    try:
        ensure_runs_schema(session)

        if args.clean:
            n_reps = session.execute(text("SELECT count(*) FROM bee_population_replicate")).scalar()
            n_apps = session.execute(text("SELECT count(*) FROM applications")).scalar()
            n_runs = session.execute(text("SELECT count(*) FROM runs")).scalar()
            session.execute(text("DELETE FROM bee_population_replicate"))
            session.execute(text("DELETE FROM applications"))
            session.commit()
            session.execute(text("DELETE FROM runs"))
            session.commit()
            logger.info(f"Cleaned DB: deleted {n_runs} runs, {n_reps} replicates, {n_apps} applications")

        imported = 0
        skipped = 0
        failed = 0

        for (hive_id, scenario, treated), mcs in sorted(groups.items()):
            treatment_label = "treated" if treated else "untreated"
            logger.info(f"Importing hive{hive_id} {treatment_label} ({len(mcs)} MCs)...")

            for mc_num, folder_path in mcs:
                try:
                    run_id = import_experiment_folder(
                        folder_path, hive_id, treated, mc_num,
                        force=args.force, session=session,
                    )
                    if run_id is not None:
                        logger.info(f"  MC{mc_num} -> run_id={run_id}")
                        imported += 1
                    else:
                        skipped += 1
                except Exception as exc:
                    logger.error(f"  MC{mc_num} failed: {exc}")
                    session.rollback()
                    failed += 1

        logger.info(f"Done: {imported} imported, {skipped} skipped, {failed} failed")
        return 0 if failed == 0 else 1

    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
