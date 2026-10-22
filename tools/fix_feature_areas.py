"""Recompute features.area_hectares in an existing BeeView DuckDB.

Earlier imports computed areas in EPSG:3857 (Web Mercator), which inflates areas by 1/cos²(latitude)
(+94 % at 44° N). This tool recomputes every feature's area from its stored WGS84 geometry using the
same equal-area logic as load_shapefile.equal_area_hectares and updates the table in place.

    python tools/fix_feature_areas.py [--db data/beeview.duckdb] [--dry-run]

Stop BeeView-server before running (DuckDB allows one writer).
"""
import argparse
import os
import sys

import duckdb
import geopandas as gpd
from shapely import wkt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from load_shapefile import equal_area_hectares  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "beeview.duckdb"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    con = duckdb.connect(args.db, read_only=args.dry_run)
    rows = con.execute("SELECT id, area_hectares, geometry FROM features").fetchall()
    ids = [r[0] for r in rows]
    old = [r[1] or 0.0 for r in rows]
    gdf = gpd.GeoDataFrame({"id": ids}, geometry=[wkt.loads(r[2]) for r in rows], crs="EPSG:4326")
    new = equal_area_hectares(gdf)
    print(f"{len(rows)} features: old sum {sum(old):.0f} ha, new sum {new.sum():.0f} ha, ratio {sum(old)/max(new.sum(), 1e-9):.3f}")
    if args.dry_run:
        return 0
    con.executemany("UPDATE features SET area_hectares = ? WHERE id = ?", [(float(a), i) for a, i in zip(new, ids)])
    con.commit()
    check = con.execute("SELECT SUM(area_hectares) FROM features").fetchone()[0]
    print(f"updated; new sum in DB {check:.0f} ha")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
