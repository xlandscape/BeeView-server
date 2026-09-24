"""Scenario discovery for xPollinator.

Scans the xPollinator scenario directory and extracts metadata (name, description, bounds)
for use in the simulation UI.
"""
import logging
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

logger = logging.getLogger("scenarios")

XPOLLINATOR_PATH = Path(os.getenv("XPOLLINATOR_PATH", os.path.join(os.path.dirname(__file__), "..", "xPollinator")))
SCENARIO_BASE = XPOLLINATOR_PATH / "scenario"


def _parse_xproject(xproject_path: Path) -> dict:
    """Parse scenario.xproject XML for metadata."""
    ns = {"s": "urn:xLandscapeModelScenarioInfo"}
    try:
        tree = ET.parse(xproject_path)
        root = tree.getroot()
        name = root.find("s:Name", ns)
        description = root.find("s:Description", ns)
        version = root.find("s:Version", ns)
        return {
            "name": name.text.strip() if name is not None and name.text else None,
            "description": description.text.strip() if description is not None and description.text else None,
            "version": version.text.strip() if version is not None and version.text else None,
        }
    except Exception as exc:
        logger.warning(f"Failed to parse {xproject_path}: {exc}")
        return {}


def _get_shapefile_bounds(scenario_path: Path) -> Optional[dict]:
    """Get geographic bounds from the scenario's shapefile."""
    geo_dir = scenario_path / "geo"
    if not geo_dir.is_dir():
        return None

    shp_files = list(geo_dir.glob("*.shp"))
    if not shp_files:
        return None

    try:
        import geopandas as gpd
        from pyproj import Transformer

        gdf = gpd.read_file(shp_files[0])
        bounds = gdf.total_bounds  # [minx, miny, maxx, maxy]

        # Transform to WGS84 if needed
        if gdf.crs and not gdf.crs.is_geographic:
            transformer = Transformer.from_crs(gdf.crs, "EPSG:4326", always_xy=True)
            min_lon, min_lat = transformer.transform(bounds[0], bounds[1])
            max_lon, max_lat = transformer.transform(bounds[2], bounds[3])
        else:
            min_lon, min_lat, max_lon, max_lat = bounds

        center_lon = (min_lon + max_lon) / 2
        center_lat = (min_lat + max_lat) / 2

        # Also provide center in projected coordinates (for BeeHaveMapCenterPoint)
        if gdf.crs and not gdf.crs.is_geographic:
            center_x = (bounds[0] + bounds[2]) / 2
            center_y = (bounds[1] + bounds[3]) / 2
        else:
            # Transform center to EPSG:3857 for BeeHave
            from pyproj import Transformer as T2
            t = T2.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
            center_x, center_y = t.transform(center_lon, center_lat)

        return {
            "min_lon": min_lon,
            "min_lat": min_lat,
            "max_lon": max_lon,
            "max_lat": max_lat,
            "center_lon": center_lon,
            "center_lat": center_lat,
            "center_x": center_x,
            "center_y": center_y,
        }
    except Exception as exc:
        logger.warning(f"Failed to read shapefile bounds for {scenario_path}: {exc}")
        return None


def list_scenarios() -> list[dict]:
    """List all available scenarios with metadata."""
    if not SCENARIO_BASE.is_dir():
        logger.warning(f"Scenario directory not found: {SCENARIO_BASE}")
        return []

    scenarios = []
    for entry in sorted(SCENARIO_BASE.iterdir()):
        if not entry.is_dir():
            continue
        # Must have either scenario.xproject or geo/ to be considered valid
        xproject = entry / "scenario.xproject"
        geo_dir = entry / "geo"
        if not xproject.exists() and not geo_dir.is_dir():
            continue

        scenario = {
            "folder_name": entry.name,
            "path": f"scenario/{entry.name}",
            "has_shapefile": bool(list(geo_dir.glob("*.shp"))) if geo_dir.is_dir() else False,
        }

        if xproject.exists():
            meta = _parse_xproject(xproject)
            scenario.update({k: v for k, v in meta.items() if v is not None})

        scenarios.append(scenario)

    return scenarios


def get_scenario_bounds(folder_name: str) -> Optional[dict]:
    """Get geographic bounds for a specific scenario."""
    scenario_path = SCENARIO_BASE / folder_name
    if not scenario_path.is_dir():
        return None
    return _get_shapefile_bounds(scenario_path)
