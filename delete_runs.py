#!/usr/bin/env python3
"""Delete imported runs (and their replicate time series) from the BeeView database.

Usage:
    python delete_runs.py --sim-id Andre_MC0 --sim-id Demo_MC0
    python delete_runs.py --batch hive36 --batch hive36_treated
    python delete_runs.py --single-user            # every run without a hive_* group
    python delete_runs.py --all --yes
Add --dry-run to list what would be deleted. Stop the BeeView server first:
DuckDB allows only one process to hold the database.
"""
from __future__ import annotations

import argparse
import sys

from sqlalchemy import text

from database import get_session
from models import Run


def select_runs(session, args) -> list[Run]:
    query = session.query(Run)
    if args.all:
        return query.all()
    selected: dict[int, Run] = {}
    for sim_id in args.sim_id or []:
        for run in query.filter(Run.sim_id == sim_id).all():
            selected[run.id] = run
    for batch in args.batch or []:
        for run in query.filter((Run.batch_sim_id == batch) | (Run.hive_group_id == batch)).all():
            selected[run.id] = run
    if args.single_user:
        for run in query.all():
            group = run.hive_group_id or run.batch_sim_id or run.sim_id or ""
            if not group.startswith("hive"):
                selected[run.id] = run
    return sorted(selected.values(), key=lambda r: r.id)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sim-id", action="append", help="exact sim_id (repeatable)")
    parser.add_argument("--batch", action="append", help="batch_sim_id or hive_group_id (repeatable)")
    parser.add_argument("--single-user", action="store_true",
                        help="runs whose group does not start with 'hive' (UI test runs, demos)")
    parser.add_argument("--all", action="store_true", help="every run")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    args = parser.parse_args()
    if not (args.sim_id or args.batch or args.single_user or args.all):
        parser.error("select runs with --sim-id, --batch, --single-user or --all")

    session = next(get_session())
    try:
        runs = select_runs(session, args)
        if not runs:
            print("no matching runs")
            return 0
        for run in runs:
            print(f"  id={run.id:4d}  {run.sim_id:32s} group={run.hive_group_id or '-':14s} "
                  f"treated={'yes' if run.treatment_on else 'no ':3s} gap={getattr(run, 'gap', None) or '-'}")
        print(f"{len(runs)} run(s) selected")
        if args.dry_run:
            return 0
        if not args.yes:
            answer = input("Delete these runs and their time series? [y/N] ").strip().lower()
            if answer != "y":
                print("aborted")
                return 1
        # DuckDB checks foreign keys per statement and cannot see child deletes that are
        # still uncommitted in the same transaction, so commit after the child tables.
        for run in runs:
            for child in ("bee_population_replicate", "applications"):
                session.execute(text(f"DELETE FROM {child} WHERE run_id = :rid"), {"rid": run.id})
            session.commit()
            session.execute(text("DELETE FROM runs WHERE id = :rid"), {"rid": run.id})
            session.commit()
        print(f"deleted {len(runs)} run(s)")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
