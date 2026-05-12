# BeeView-server

BeeView-server is the FastAPI backend that loads xPollinator simulation outputs into a DuckDB database and serves them to the [BeeView](../BeeView/) frontend via a REST API.

## Architecture

```
xPollinator run output
    → import_run.py (or legacy file loading)
    → DuckDB (data/beeview.duckdb)
    → FastAPI (port 32000)
    → BeeView frontend
```

The server handles two types of data:

1. **Landscape data** (legacy mode) — shapefile geometries, nectar/pollen timeseries from HDF5, vegetation mappings. Loaded once from files in `data/`.
2. **Run data** (import mode) — bee colony population timeseries from BEEHAVE output CSVs, imported per-run with metadata (hive location, treatment status, MC replicates).

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Place landscape data files in data/ (see Data Requirements)

# 3. Start with a fresh database
python manage_db.py
# Choose option 1: Delete database and start server

# 4. Import xPollinator runs
python import_run.py path/to/xPollinator/run/MySimID

# 5. Open BeeView at http://localhost:8083
```

## Documentation

- [Installation](installation.md) — setting up the Python environment and dependencies
- [Data Requirements](data-requirements.md) — which files are needed from xPollinator
- [Importing Runs](importing-runs.md) — how `import_run.py` works and what it reads
- [Batch Processing](batch-processing.md) — preparing multi-hive, multi-MC experiment folders
- [Database Management](database.md) — resetting, inspecting, and managing the DuckDB database
- [API Reference](api-reference.md) — key endpoints served to the BeeView frontend
