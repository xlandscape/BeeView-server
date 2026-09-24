"""
In-memory cache of the landscape GeoJSON served by /geojson and /geojson/viewport.

The raw `features` table holds ~25k multipolygons as full-precision WKT
(~100 MB as GeoJSON). Serving that on every page load, and re-parsing every
WKT string on every viewport query, dominated BeeView's load time.

This module builds the served representation exactly once:

  * geometries are simplified (topology preserving) and coordinates rounded,
  * every feature is pre-serialized to a compact JSON string,
  * the full FeatureCollection is pre-gzipped so /geojson costs one memcpy,
  * an STRtree over the simplified geometries answers viewport queries in ms.

The result is persisted to ``data/cache`` and keyed by a fingerprint of the
``features`` table plus the simplification settings, so restarts are fast and
re-imports invalidate the cache automatically.

Environment variables:
  GEOJSON_SIMPLIFY_TOLERANCE  degrees, default 0.00001 (~1 m). 0 disables.
  GEOJSON_PRECISION           decimal places kept, default 6 (~0.1 m).
  GEOJSON_CACHE_DIR           default data/cache
"""

import gzip
import hashlib
import json
import logging
import os
import pickle
import threading
import time
from typing import List, Optional, Tuple

import numpy as np
import shapely
from shapely import wkt
from shapely.geometry import box, mapping
from shapely.strtree import STRtree
from sqlalchemy import text

from database import get_session

logger = logging.getLogger(__name__)

CACHE_FORMAT_VERSION = 2

SIMPLIFY_TOLERANCE = float(os.getenv("GEOJSON_SIMPLIFY_TOLERANCE", "0.00001"))
PRECISION = int(os.getenv("GEOJSON_PRECISION", "6"))
CACHE_DIR = os.getenv("GEOJSON_CACHE_DIR", os.path.join("data", "cache"))

_FEATURE_QUERY = text(
    "SELECT feature_id, name, l1_code, l1_label, l2_code, l2_label, "
    "l3_code, l3_label, area_hectares, geometry FROM features ORDER BY feature_id"
)
_FINGERPRINT_QUERY = text(
    "SELECT count(*), coalesce(sum(length(geometry)), 0), coalesce(max(feature_id), 0) FROM features"
)


class GeometryCache:
    def __init__(self):
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._error: Optional[Exception] = None

        self.fingerprint: Optional[str] = None
        self.etag: Optional[str] = None
        self.feature_json: List[str] = []
        self.feature_ids: np.ndarray = np.zeros(0, dtype=np.int64)
        self.tree: Optional[STRtree] = None
        self.full_bytes: bytes = b""
        self.full_gzip: bytes = b""
        self.built_at: Optional[float] = None

    # ------------------------------------------------------------------ status
    @property
    def ready(self) -> bool:
        return self._ready.is_set() and self._error is None

    def wait_ready(self, timeout: Optional[float] = None) -> bool:
        """Block until the cache is built (or failed). Returns readiness."""
        self._ready.wait(timeout)
        return self.ready

    def stats(self) -> dict:
        return {
            "ready": self.ready,
            "error": str(self._error) if self._error else None,
            "features": len(self.feature_json),
            "bytes": len(self.full_bytes),
            "gzip_bytes": len(self.full_gzip),
            "simplify_tolerance": SIMPLIFY_TOLERANCE,
            "precision": PRECISION,
            "fingerprint": self.fingerprint,
        }

    # ------------------------------------------------------------------- build
    def start_background_build(self) -> None:
        threading.Thread(target=self.build, name="geojson-cache-build", daemon=True).start()

    def build(self) -> None:
        with self._lock:
            if self.ready:
                return
            try:
                self._build_locked()
                self._error = None
            except Exception as exc:  # pragma: no cover - logged, endpoints fall back
                logger.exception("GEOJSON CACHE: build failed, endpoints will use the slow path")
                self._error = exc
            finally:
                self._ready.set()

    def _build_locked(self) -> None:
        t0 = time.time()
        fingerprint = self._compute_fingerprint()
        cache_path = self._cache_path()

        payload = self._load_from_disk(cache_path, fingerprint)
        if payload is None:
            logger.info(
                "GEOJSON CACHE: building (tolerance=%s, precision=%s) ...",
                SIMPLIFY_TOLERANCE, PRECISION,
            )
            payload = self._build_from_db(fingerprint)
            self._save_to_disk(cache_path, payload)
        else:
            logger.info("GEOJSON CACHE: loaded from %s", cache_path)

        self._install(payload)
        logger.info(
            "GEOJSON CACHE: ready in %.1fs - %d features, %.1f MB raw, %.1f MB gzip",
            time.time() - t0, len(self.feature_json),
            len(self.full_bytes) / 1e6, len(self.full_gzip) / 1e6,
        )

    def _compute_fingerprint(self) -> str:
        session = next(get_session())
        try:
            count, total_len, max_id = session.execute(_FINGERPRINT_QUERY).one()
        finally:
            session.close()
        raw = f"v{CACHE_FORMAT_VERSION}|{count}|{total_len}|{max_id}|{SIMPLIFY_TOLERANCE}|{PRECISION}"
        return hashlib.sha1(raw.encode()).hexdigest()

    def _cache_path(self) -> str:
        return os.path.join(CACHE_DIR, f"landscape_t{SIMPLIFY_TOLERANCE:g}_p{PRECISION}.pkl")

    def _build_from_db(self, fingerprint: str) -> dict:
        session = next(get_session())
        try:
            rows = session.execute(_FEATURE_QUERY).fetchall()
        finally:
            session.close()

        feature_json: List[str] = []
        wkb: List[bytes] = []
        feature_ids: List[int] = []
        skipped = 0
        for row in rows:
            try:
                geom = wkt.loads(row.geometry)
            except Exception as exc:
                logger.warning("GEOJSON CACHE: skipping feature %s (bad WKT: %s)", row.feature_id, exc)
                skipped += 1
                continue
            geom = _simplify(geom)
            props = {
                "name": row.name,
                "L1_code": row.l1_code,
                "L1_label": row.l1_label,
                "L2_code": row.l2_code,
                "L2_label": row.l2_label,
                "L3_code": row.l3_code,
                "L3_label": row.l3_label,
                "area_hectares": row.area_hectares,
            }
            feature = {"type": "Feature", "id": row.feature_id, "properties": props, "geometry": mapping(geom)}
            feature_json.append(json.dumps(feature, separators=(",", ":")))
            wkb.append(shapely.to_wkb(geom))
            feature_ids.append(int(row.feature_id))

        if skipped:
            logger.warning("GEOJSON CACHE: skipped %d features with invalid geometry", skipped)

        full_bytes = _assemble(feature_json)
        return {
            "version": CACHE_FORMAT_VERSION,
            "fingerprint": fingerprint,
            "feature_json": feature_json,
            "feature_ids": feature_ids,
            "wkb": wkb,
            "full_gzip": gzip.compress(full_bytes, compresslevel=6),
        }

    def _install(self, payload: dict) -> None:
        self.fingerprint = payload["fingerprint"]
        self.etag = f'"{self.fingerprint[:16]}"'
        self.feature_json = payload["feature_json"]
        self.feature_ids = np.asarray(payload["feature_ids"], dtype=np.int64)
        self.full_bytes = _assemble(self.feature_json)
        self.full_gzip = payload["full_gzip"]
        self.tree = STRtree(shapely.from_wkb(payload["wkb"]))
        self.built_at = time.time()

    # -------------------------------------------------------------------- disk
    @staticmethod
    def _load_from_disk(path: str, fingerprint: str) -> Optional[dict]:
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "rb") as fh:
                payload = pickle.load(fh)
        except Exception as exc:
            logger.warning("GEOJSON CACHE: could not read %s (%s), rebuilding", path, exc)
            return None
        if payload.get("version") != CACHE_FORMAT_VERSION or payload.get("fingerprint") != fingerprint:
            logger.info("GEOJSON CACHE: %s is stale, rebuilding", path)
            return None
        return payload

    @staticmethod
    def _save_to_disk(path: str, payload: dict) -> None:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "wb") as fh:
                pickle.dump(payload, fh, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp, path)
            logger.info("GEOJSON CACHE: saved to %s", path)
        except Exception as exc:
            logger.warning("GEOJSON CACHE: could not persist cache to %s: %s", path, exc)

    # ----------------------------------------------------------------- queries
    def feature_ids_in_bbox(self, min_lng: float, min_lat: float, max_lng: float, max_lat: float) -> List[int]:
        idx = self.tree.query(box(min_lng, min_lat, max_lng, max_lat), predicate="intersects")
        return self.feature_ids[np.sort(idx)].tolist()

    def viewport(self, min_lng: float, min_lat: float, max_lng: float, max_lat: float) -> Tuple[bytes, int]:
        """Return the FeatureCollection body (bytes) for features intersecting the bbox."""
        bbox = box(min_lng, min_lat, max_lng, max_lat)
        idx = self.tree.query(bbox, predicate="intersects")
        idx = np.sort(idx)
        selected = [self.feature_json[i] for i in idx]
        viewport = json.dumps(
            {
                "bounds": [min_lng, min_lat, max_lng, max_lat],
                "simplify_tolerance": SIMPLIFY_TOLERANCE,
                "feature_count": len(selected),
            },
            separators=(",", ":"),
        )
        body = b'{"type":"FeatureCollection","features":[' + ",".join(selected).encode("utf-8") + b'],"viewport":' + viewport.encode("utf-8") + b"}"
        return body, len(selected)


def _simplify(geom):
    if SIMPLIFY_TOLERANCE > 0:
        simplified = geom.simplify(SIMPLIFY_TOLERANCE, preserve_topology=True)
        if not simplified.is_empty and simplified.is_valid:
            geom = simplified
    if PRECISION >= 0:
        geom = shapely.transform(geom, lambda coords: np.round(coords, PRECISION))
    return geom


def _assemble(feature_json: List[str]) -> bytes:
    return b'{"type":"FeatureCollection","features":[' + ",".join(feature_json).encode("utf-8") + b"]}"


# Module-level singleton used by main.py
cache = GeometryCache()
