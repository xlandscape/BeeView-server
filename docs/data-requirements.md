# Data Requirements

BeeView-server needs two categories of data from xPollinator:

1. **Landscape data** — spatial features, nectar/pollen timeseries, vegetation mappings
2. **Run data** — BEEHAVE colony simulation outputs, one per simulation run

## Landscape data (placed in `data/`)

These files describe the landscape and are loaded once when the server starts for the first time. They come from the xPollinator scenario and a single simulation run.

### Required files

| File | Source in xPollinator | Content |
|------|----------------------|---------|
| `lulc.shp` (+ `.dbf`, `.prj`, `.shx`, `.cpg`) | `scenario/<name>/geo/lulc.*` | Land use / land cover polygons with L1/L2/L3 classification |
| `arr.dat` | `run/<SimID>/mcs/<MC_ID>/store/arr.dat` | HDF5 data store containing nectar, pollen, vegetation, and feature IDs |
| `vegetation classes.json` | `scenario/<name>/` or bundled with the model | Maps vegetation class IDs to human-readable names |
| `land cover to vegetation default mapping.csv` | Bundled with the model | Maps LULC codes to vegetation classes |

### Optional files

| File | Source | Content |
|------|--------|---------|
| `output.csv` | `run/<SimID>/mcs/<MC_ID>/processing/BeeHave/output.csv` | Legacy single-run BEEHAVE output (only needed if not using `import_run.py`) |

!!! note
    `applications.txt` does **not** need to be placed in `data/`. Batch import stores application events in DuckDB (`applications` table). Runtime reads from DB first; legacy file fallback (`source_path/.../applications.txt` or `data/applications.txt`) exists for backward compatibility.

    For deployment, this means you can distribute `data/beeview.duckdb` directly and do not need to ship `experiments/`.

### HDF5 data paths in `arr.dat`

The server reads these datasets from the HDF5 file:

| HDF5 path | Shape | Content |
|-----------|-------|---------|
| `LandscapeScenario/FeatureIds` | `(N,)` | Integer array mapping array index to feature ID |
| `Vegetation/Vegetation` | `(N,)` | Vegetation class assignment per feature |
| `BeeForage/Nectar` | `(N, 365)` | Nectar availability in L/(m²·day) per feature per day |
| `BeeForage/Pollen` | `(N, 365)` | Pollen availability in g/(m²·day) per feature per day |

Where `N` is the number of landscape features.

### How to copy landscape files

From a completed xPollinator run:

```bash
# Shapefile (all components)
cp xPollinator/scenario/Tarn-et-Garonne/geo/lulc.* BeeView-server/data/

# HDF5 store (from any MC folder — landscape data is the same across MCs)
cp xPollinator/run/MySimID/mcs/X3*/store/arr.dat BeeView-server/data/

# Vegetation classes (from the scenario or model)
cp "xPollinator/scenario/Tarn-et-Garonne/vegetation classes.json" BeeView-server/data/

# Land cover mapping
cp "xPollinator/scenario/Tarn-et-Garonne/land cover to vegetation default mapping.csv" BeeView-server/data/
```

## Run data (imported via `import_run.py`)

Each xPollinator simulation run is imported separately using `import_run.py`. The import script reads from the xPollinator `run/<SimID>/` folder structure.

### Expected folder structure

```
run/<SimID>/
├── user.xml                           ← copy of the .xrun parameter file
└── mcs/
    ├── X3ABCDEF.../                   ← MC folder 0
    │   └── processing/
    │       └── BeeHave/
    │           ├── output.csv         ← BEEHAVE colony metrics
    │           └── applications.txt   ← pesticide applications (if treated)
    ├── X3GHIJKL.../                   ← MC folder 1
    │   └── processing/BeeHave/...
    └── ...                            ← more MC folders
```

### `user.xml` parameters read by the importer

| XML element | Used for |
|-------------|----------|
| `<SimID>` | Unique run identifier, becomes `batch_sim_id` |
| `<Project>` | Scenario path reference |
| `<HiveGroupId>` | Groups runs at the same hive location |
| `<BeeHaveMapCenterPointX>` | Hive easting (projected CRS) |
| `<BeeHaveMapCenterPointY>` | Hive northing (projected CRS) |
| `<NumberBeeHaveReplicates>` | Expected number of BEEHAVE stochastic replicates |
| `<BeeHaveRandomSeed>` | Random seed for paired-run comparisons |
| `<MinNumberApplications>` | If max > 0, the run is flagged as "treated" |
| `<MaxNumberApplications>` | Determines treatment status |
| `<SimulationStart>` | Start date (YYYY-MM-DD) for multi-year axis labels |

### `output.csv` format

BEEHAVE BehaviorSpace CSVs have **6 metadata header rows** followed by the column header on row 7. Key columns:

| Column | Meaning |
|--------|---------|
| `[run number]` | Replicate index (from `steppedValueSet` on `RAND_SEED`) |
| `[step]` | Simulation day |
| `TotalIHbees` | Number of in-hive worker bees |
| `TotalForagers` | Number of forager bees |
| `TotalEggs` / `TotalDroneEggs` | Worker and drone eggs |
| `TotalLarvae` / `TotalDroneLarvae` | Worker and drone larvae |
| `TotalPupae` / `TotalDronePupae` | Worker and drone pupae |
| `HoneyEnergyStore` | Honey stores (energy units) |
| `PollenStore_g` | Pollen stores (grams) |

The importer computes **derived (summed) metrics** automatically:

- `TotalIHbees + TotalForagers` → total adult workers
- `TotalDroneEggs + TotalEggs` → all eggs
- `TotalDroneLarvae + TotalLarvae` → all larvae
- `TotalDronePupae + TotalPupae` → all pupae
- Sum of all eight → total colony size

See [Importing Runs](importing-runs.md) for usage details.
