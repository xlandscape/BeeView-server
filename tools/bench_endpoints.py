import json
import time
import urllib.request
import gzip
import urllib.parse

BASE = "http://localhost:32000"


def get(path, accept_gzip=True):
    req = urllib.request.Request(BASE + path)
    if accept_gzip:
        req.add_header("Accept-Encoding", "gzip")
    t = time.perf_counter()
    with urllib.request.urlopen(req, timeout=120) as r:
        body = r.read()
        enc = r.headers.get("Content-Encoding", "")
    dt = time.perf_counter() - t
    wire = len(body)
    if enc == "gzip":
        body = gzip.decompress(body)
    return dt, wire, body


runs = json.loads(get("/api/runs")[2])
runs = runs.get("runs", runs) if isinstance(runs, dict) else runs
by_sim = {r["sim_id"]: r for r in runs}

# pairs: hiveNN_MC0 (untreated) vs hiveNN_treated_MC0
pairs = []
for sim, r in by_sim.items():
    if sim.startswith("hive") and sim.endswith("_MC0") and "treated" not in sim:
        hive = sim[: -len("_MC0")]
        t = by_sim.get(f"{hive}_treated_MC0")
        if t:
            pairs.append((r["id"], t["id"]))
pairs.sort()
print(f"{len(pairs)} hive pairs")
bs = ",".join(str(b) for b, _ in pairs)
ss = ",".join(str(s) for _, s in pairs)
metric = "TotalIHbees + TotalForagers"
b0, s0 = pairs[0] if pairs else (runs[0]["id"], runs[1]["id"])

tests = [
    ("/geojson", "/geojson"),
    ("forage index", "/api/forage/index"),
    ("forage nectar", "/api/forage/nectar.f32"),
    ("runs", "/api/runs"),
    ("veg mapping", "/api/features/vegetation-mapping"),
    ("bee metrics", "/api/bee-population/metrics"),
    ("applications", f"/api/applications?run_id={s0}"),
    ("replicates 1 run", f"/api/bee-population/replicates?run_id={s0}"),
    ("exposure ts", f"/api/exposure/timeseries?run_id={s0}"),
    ("compare relative", f"/api/compare/relative?baseline_id={b0}&scenario_id={s0}&metric={urllib.parse.quote(metric)}"),
    ("reduction-matrix all pairs", f"/api/compare/reduction-matrix?baseline_ids={bs}&scenario_ids={ss}&metric={urllib.parse.quote(metric)}"),
    ("reduction-matrix hive_mean", f"/api/compare/reduction-matrix?baseline_ids={bs}&scenario_ids={ss}&metric={urllib.parse.quote(metric)}&spatial_scope=hive_mean"),
    ("ed-matrix all pairs", f"/api/compare/ed-matrix?baseline_ids={bs}&scenario_ids={ss}&metric={urllib.parse.quote(metric)}"),
    ("survival all pairs", f"/api/compare/survival?baseline_ids={bs}&scenario_ids={ss}"),
]
import urllib.parse  # noqa: E402  (used above lazily)

for name, path in tests:
    try:
        # warm + measured
        get(path)
        dt, wire, body = get(path)
        print(f"{name:30s} {dt*1000:8.0f} ms  wire {wire/1024:9.1f} KB  raw {len(body)/1024:9.1f} KB")
    except Exception as e:  # noqa: BLE001
        print(f"{name:30s} ERROR {e}")
