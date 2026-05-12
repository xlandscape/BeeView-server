# Database Management

BeeView-server uses **DuckDB**, an embedded analytical database stored as a single file at `data/beeview.duckdb`.

## Database schema

### Core landscape tables

These tables are populated from the landscape data files in `data/` on first startup:

| Table | Content | Source |
|-------|---------|--------|
| `feature_ids` | Maps HDF5 array index → shapefile feature ID | `arr.dat` (`LandscapeScenario/FeatureIds`) |
| `features` | Polygon geometries with L1/L2/L3 land-use labels and area | `lulc.shp` |
| `vegetation_class_mapping` | Vegetation name ↔ class ID lookup | `vegetation classes.json` |
| `vegetation` | Vegetation class assigned to each feature | `arr.dat` (`Vegetation/Vegetation`) |
| `nectar` | Nectar timeseries per feature (pickled numpy array) | `arr.dat` (`BeeForage/Nectar`) |
| `pollen` | Pollen timeseries per feature (pickled numpy array) | `arr.dat` (`BeeForage/Pollen`) |
| `bee_population` | Legacy single-run colony metrics (pickled numpy array) | `output.csv` |

### Run tables

These tables are populated by `import_run.py`:

| Table | Content |
|-------|---------|
| `runs` | One row per imported MC folder — metadata including hive coordinates, treatment status, and MC index |
| `bee_population_replicate` | One row per (run, replicate, metric) — the timeseries as a pickled numpy array |

## `manage_db.py` — interactive management

```bash
python manage_db.py
```

| Option | Action |
|--------|--------|
| **1** | Delete the database file and start the server with an empty database. Legacy data loading is skipped — use `import_run.py` to populate. |
| **2** | Start the server using the existing database. If no database exists, it creates one and loads legacy data files from `data/`. |
| **3** | Show database info: file size, record counts per table. |
| **4** | Exit. |

## Resetting the database

To start fresh:

```bash
# Option A: Use manage_db.py
python manage_db.py
# Choose option 1

# Option B: Delete manually
rm data/beeview.duckdb
# Then start the server — it will recreate tables
```

!!! warning
    Deleting the database removes all imported run data. You will need to re-import runs with `import_run.py`.

## Skipping legacy data loading

When using `import_run.py` exclusively (no legacy `data/output.csv`), set the environment variable to prevent the server from trying to load legacy files:

```bash
SKIP_LEGACY_DATA_LOADING=1 python main.py
```

Or use `manage_db.py` option 1, which sets this automatically.

The server will still create tables and load landscape data (shapefile, HDF5, vegetation mappings), but will skip the legacy `output.csv` loading.

## Inspecting the database

### From `manage_db.py`

Choose option 3 to see table record counts and file size.

### From Python

```python
import duckdb

con = duckdb.connect("data/beeview.duckdb", read_only=True)
# List tables
print(con.sql("SHOW TABLES").fetchall())
# Count runs
print(con.sql("SELECT COUNT(*) FROM runs").fetchone())
# List imported runs
print(con.sql("SELECT id, sim_id, hive_group_id, treatment_on, outer_mc_id FROM runs ORDER BY id").fetchdf())
con.close()
```

## Timeseries storage format

All timeseries data (nectar, pollen, bee population) is stored as **pickled numpy arrays** in `BLOB` columns. Each array is a 1-D `float32` array with one value per simulation day (typically 365 or 366 values).

To read a timeseries manually:

```python
import pickle
# After querying a row from bee_population_replicate:
timeseries = pickle.loads(row.timeseries)  # numpy.ndarray, shape (n_days,)
```

!!! warning "Pickle security"
    Python's `pickle` module can execute arbitrary code during deserialization. Only unpickle data from trusted sources (i.e. data you imported yourself).
