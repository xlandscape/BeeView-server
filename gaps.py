"""GAP (Good Agricultural Practice) presets for xPollinator simulations.

The catalog lives in the xPollinator repository at model/variant/gaps.json so that the model and
the UI share one source of truth. Each preset bundles the exposure parameters of a crop use with
the toxicity endpoints of the substance. `expand_gap` turns a preset id into the flat parameter
dict that the .xrun file needs.
"""
import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("gaps")

XPOLLINATOR_PATH = Path(os.getenv("XPOLLINATOR_PATH", os.path.join(os.path.dirname(__file__), "..", "xPollinator"))).resolve()
GAPS_FILE = Path(os.getenv("GAPS_FILE", XPOLLINATOR_PATH / "model" / "variant" / "gaps.json"))

DEFAULT_GAP_ID = "default"

# .xrun parameter names carried by a preset, in the order they are written to the file.
GAP_PARAM_KEYS = [
    "AppliedVegetationId", "FirstDayOfYearApplications", "LastDayOfYearApplications", "ExposurePeriod",
    "ContactToxicityMean", "ContactToxicityStd", "ConcNectarMean", "ConcNectarStd",
    "ConcPollenMean", "ConcPollenStd", "ResidueUnitDose", "PlantDT50",
    "ForagerOralLD50", "ForagerOralSlope", "ForagerContactLD50", "ForagerContactSlope",
    "LarvaeOralLD50", "LarvaeOralSlope",
]

_cache: dict = {"mtime": None, "catalog": None}


def _load_catalog() -> dict:
    """Load gaps.json, re-reading it when the file changed on disk."""
    try:
        mtime = GAPS_FILE.stat().st_mtime
    except FileNotFoundError:
        logger.error("GAP catalog not found: %s", GAPS_FILE)
        return {"parameters": {}, "gaps": []}
    if _cache["catalog"] is None or _cache["mtime"] != mtime:
        with open(GAPS_FILE, encoding="utf-8") as fh:
            _cache["catalog"] = json.load(fh)
        _cache["mtime"] = mtime
        logger.info("Loaded %d GAP presets from %s", len(_cache["catalog"].get("gaps", [])), GAPS_FILE)
    return _cache["catalog"]


def list_gaps() -> list[dict]:
    """All presets with their metadata and parameters, for the UI dropdown and detail card."""
    return list(_load_catalog().get("gaps", []))


def gap_parameter_info() -> dict:
    """Unit and description per parameter key, for display in the UI."""
    return dict(_load_catalog().get("parameters", {}))


def get_gap(gap_id: str) -> Optional[dict]:
    for gap in _load_catalog().get("gaps", []):
        if gap.get("id") == gap_id:
            return gap
    return None


def expand_gap(params: dict) -> tuple[dict, Optional[str]]:
    """Merge the preset selected by params["GAP"] into params.

    Values that the caller already supplied for individual keys take precedence over the preset,
    so a request can start from a preset and override single numbers. Returns the merged dict and
    an error message (or None).
    """
    gap_id = params.get("GAP") or DEFAULT_GAP_ID
    gap = get_gap(gap_id)
    if gap is None:
        available = ", ".join(g["id"] for g in list_gaps())
        return params, f"Unknown GAP '{gap_id}'. Available: {available}"
    merged = dict(params)
    merged["GAP"] = gap_id
    for key in GAP_PARAM_KEYS:
        if merged.get(key) is None and key in gap["params"]:
            merged[key] = gap["params"][key]
    missing = [key for key in GAP_PARAM_KEYS if merged.get(key) is None]
    if missing:
        return merged, f"GAP '{gap_id}' is missing parameters: {', '.join(missing)}"
    return merged, None
