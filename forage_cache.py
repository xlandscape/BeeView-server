"""
In-memory nectar/pollen matrices.

The ``nectar`` and ``pollen`` tables store one pickled float32[365] per
feature. Every slider-driven endpoint used to unpickle all ~25k rows to pull
out a single day, and ``/api/timeseries/averages`` did the same to average
them. Here both tables are loaded once into (features x days) float32
matrices so those requests become a column slice or a vectorised mean.

The matrices are also served whole (``/api/forage/{kind}.f32``): the values
are highly repetitive, so 37 MB of float32 gzips to well under 1 MB, which
lets the browser scrub through the year without any further requests.
"""

import gzip
import hashlib
import logging
import pickle
import threading
import time
from datetime import datetime
from typing import Dict, Iterable, Optional

import numpy as np
from sqlalchemy import text

from database import get_session

logger = logging.getLogger(__name__)

KINDS = ("nectar", "pollen")

_QUERIES = {
    "nectar": text(
        "SELECT fi.feature_id, n.timeseries FROM nectar n "
        "JOIN feature_ids fi ON n.feature_index = fi.index ORDER BY fi.feature_id"
    ),
    "pollen": text(
        "SELECT fi.feature_id, p.timeseries FROM pollen p "
        "JOIN feature_ids fi ON p.feature_index = fi.index ORDER BY fi.feature_id"
    ),
}


def parse_day_index(date: str, n_days: int) -> int:
    """Accept a 1-based day-of-year integer or an ISO date; return a 0-based index."""
    try:
        idx = int(date) - 1
    except ValueError:
        try:
            idx = datetime.strptime(date, "%Y-%m-%d").timetuple().tm_yday - 1
        except ValueError:
            idx = 0
    if idx < 0 or idx >= n_days:
        idx = 0
    return idx


class ForageCache:
    def __init__(self):
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._error: Optional[Exception] = None

        self.feature_ids: np.ndarray = np.zeros(0, dtype=np.int32)
        self.row_by_feature_id: Dict[int, int] = {}
        self.matrix: Dict[str, np.ndarray] = {}
        self.gzip_bytes: Dict[str, bytes] = {}
        self.max_values: Dict[str, np.ndarray] = {}
        self.n_days = 365
        self.etag: Optional[str] = None
        self.built_at: Optional[float] = None

    # ------------------------------------------------------------------ status
    @property
    def ready(self) -> bool:
        return self._ready.is_set() and self._error is None

    def wait_ready(self, timeout: Optional[float] = None) -> bool:
        self._ready.wait(timeout)
        return self.ready

    def stats(self) -> dict:
        return {
            "ready": self.ready,
            "error": str(self._error) if self._error else None,
            "features": int(len(self.feature_ids)),
            "days": self.n_days,
            "gzip_bytes": {k: len(v) for k, v in self.gzip_bytes.items()},
            "etag": self.etag,
        }

    # ------------------------------------------------------------------- build
    def start_background_build(self) -> None:
        threading.Thread(target=self.build, name="forage-cache-build", daemon=True).start()

    def build(self) -> None:
        with self._lock:
            if self.ready:
                return
            try:
                self._build_locked()
                self._error = None
            except Exception as exc:  # pragma: no cover - logged, endpoints fall back
                logger.exception("FORAGE CACHE: build failed, endpoints will use the slow path")
                self._error = exc
            finally:
                self._ready.set()

    def _build_locked(self) -> None:
        t0 = time.time()
        series: Dict[str, Dict[int, np.ndarray]] = {}
        session = next(get_session())
        try:
            for kind in KINDS:
                per_feature = {}
                for row in session.execute(_QUERIES[kind]):
                    arr = np.asarray(pickle.loads(row.timeseries), dtype=np.float32).ravel()
                    per_feature[int(row.feature_id)] = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
                series[kind] = per_feature
        finally:
            session.close()

        all_ids = sorted(set().union(*(s.keys() for s in series.values())))
        lengths = [len(a) for s in series.values() for a in s.values()]
        n_days = max(lengths) if lengths else 365

        feature_ids = np.asarray(all_ids, dtype=np.int32)
        row_by_id = {int(fid): i for i, fid in enumerate(all_ids)}
        matrices = {}
        for kind in KINDS:
            m = np.zeros((len(all_ids), n_days), dtype=np.float32)
            for fid, arr in series[kind].items():
                m[row_by_id[fid], : len(arr)] = arr[:n_days]
            matrices[kind] = m

        digest = hashlib.sha1()
        digest.update(feature_ids.tobytes())
        for kind in KINDS:
            digest.update(matrices[kind].tobytes())

        self.feature_ids = feature_ids
        self.row_by_feature_id = row_by_id
        self.matrix = matrices
        self.n_days = n_days
        self.max_values = {k: m.max(axis=1) if m.size else np.zeros(0, np.float32) for k, m in matrices.items()}
        self.gzip_bytes = {k: gzip.compress(np.ascontiguousarray(m).tobytes(), compresslevel=6) for k, m in matrices.items()}
        self.etag = f'"{digest.hexdigest()[:16]}"'
        self.built_at = time.time()
        logger.info(
            "FORAGE CACHE: ready in %.1fs - %d features x %d days, gzip %s",
            time.time() - t0, len(feature_ids), n_days,
            {k: f"{len(v) / 1e6:.2f} MB" for k, v in self.gzip_bytes.items()},
        )

    # ----------------------------------------------------------------- queries
    def rows_for(self, feature_ids: Optional[Iterable[int]]) -> Optional[np.ndarray]:
        """Row indices for the given feature ids (None = all rows). Unknown ids are ignored."""
        if feature_ids is None:
            return None
        rows = [self.row_by_feature_id[int(f)] for f in feature_ids if int(f) in self.row_by_feature_id]
        return np.asarray(rows, dtype=np.int64)

    def day_values(self, kind: str, date: str, feature_ids: Optional[Iterable[int]] = None):
        """[(feature_id, value)] for one day, optionally restricted to feature ids."""
        idx = parse_day_index(date, self.n_days)
        rows = self.rows_for(feature_ids)
        m = self.matrix[kind]
        if rows is None:
            return zip(self.feature_ids.tolist(), m[:, idx].tolist())
        return zip(self.feature_ids[rows].tolist(), m[rows, idx].tolist())

    def maxima(self, kind: str, feature_ids: Optional[Iterable[int]] = None):
        rows = self.rows_for(feature_ids)
        mx = self.max_values[kind]
        if rows is None:
            return zip(self.feature_ids.tolist(), mx.tolist())
        return zip(self.feature_ids[rows].tolist(), mx[rows].tolist())

    def series(self, kind: str, feature_id: int) -> Optional[list]:
        row = self.row_by_feature_id.get(int(feature_id))
        if row is None:
            return None
        return self.matrix[kind][row].tolist()

    def averages(self, feature_ids: Optional[Iterable[int]], include_nectar: bool, include_pollen: bool) -> list:
        rows = self.rows_for(feature_ids)
        out = []
        means = {}
        for kind, include in (("nectar", include_nectar), ("pollen", include_pollen)):
            m = self.matrix[kind]
            if not include or m.size == 0 or (rows is not None and len(rows) == 0):
                means[kind] = np.zeros(self.n_days, dtype=np.float64)
            else:
                means[kind] = (m if rows is None else m[rows]).mean(axis=0, dtype=np.float64)
        for day in range(self.n_days):
            out.append({"day": day + 1, "nectar_avg": float(means["nectar"][day]), "pollen_avg": float(means["pollen"][day])})
        while len(out) < 365:
            out.append({"day": len(out) + 1, "nectar_avg": 0.0, "pollen_avg": 0.0})
        return out


cache = ForageCache()
