# Importing Runs

The `import_run.py` script imports an xPollinator simulation run into the BeeView database. It reads the run's `user.xml` metadata and BEEHAVE output CSVs, then stores them as structured records in DuckDB.

## Basic usage

```bash
python import_run.py path/to/xPollinator/run/MySimID
```

This:

1. Reads `user.xml` from the run folder to extract metadata (hive location, treatment status, etc.)
2. Finds all MC folders under `mcs/` (folders starting with `X3`)
3. Parses each MC folder's `processing/BeeHave/output.csv`
4. Creates one `Run` database record per MC folder
5. Stores each BEEHAVE replicate's timeseries as a `BeePopulationReplicate` record

### Options

| Flag | Effect |
|------|--------|
| `--force` | Replace existing runs with the same SimID (deletes old records first) |
| `-v` / `--verbose` | Enable debug-level logging |

### Examples

```bash
# Import a single run
python import_run.py ../xPollinator/run/hive01_untreated

# Re-import (overwrite existing data)
python import_run.py ../xPollinator/run/hive01_treated --force

# Verbose output for debugging
python import_run.py ../xPollinator/run/TestRun -v
```

## What gets created in the database

### `runs` table — one row per MC folder

Each MC folder within the run becomes a separate `Run` record:

| Column | Example | Source |
|--------|---------|--------|
| `sim_id` | `hive01_treated_MC0` | `<SimID>` + `_MC<index>` |
| `batch_sim_id` | `hive01_treated` | Original `<SimID>` from user.xml |
| `outer_mc_id` | `0` | Sequential index of the MC folder |
| `mc_folder_name` | `X3ER7MMTRUFYD2S5PB` | Actual folder name |
| `hive_group_id` | `hive01` | `<HiveGroupId>` or SimID with `_treated`/`_untreated` stripped |
| `treatment_on` | `true` | `true` if `<MaxNumberApplications>` > 0 |
| `hive_x`, `hive_y` | `127406.9`, `5482559.8` | Projected coordinates from user.xml |
| `hive_lon`, `hive_lat` | `1.175`, `44.120` | Transformed to WGS84 (EPSG:4326) |
| `n_replicates` | `10` | Number of BEEHAVE replicates found in output.csv |
| `random_seed` | `42` | `<BeeHaveRandomSeed>` |
| `sim_start` | `2020-01-01` | `<SimulationStart>` (if present) |

### `bee_population_replicate` table — one row per replicate × metric

For each MC folder, the importer stores one timeseries per (replicate, metric) combination:

| Column | Content |
|--------|---------|
| `run_id` | Foreign key to `runs.id` |
| `replicate_idx` | BEEHAVE `[run number]` (0-based replicate index) |
| `metric_name` | e.g. `TotalIHbees + TotalForagers` |
| `timeseries` | Pickled numpy float32 array (one value per simulation day) |

## How MC folders are handled

A single xPollinator `<SimID>` may contain **multiple Monte Carlo landscape realisations**, each in a separate `X3*` folder under `mcs/`. The importer creates one `Run` per MC folder, linked by `batch_sim_id`:

```
run/hive01_treated/
├── user.xml
└── mcs/
    ├── X3ABC.../output.csv  → Run(sim_id="hive01_treated_MC0", outer_mc_id=0)
    ├── X3DEF.../output.csv  → Run(sim_id="hive01_treated_MC1", outer_mc_id=1)
    └── X3GHI.../output.csv  → Run(sim_id="hive01_treated_MC2", outer_mc_id=2)
```

## How BEEHAVE replicates are handled

Within each MC folder's `output.csv`, multiple BEEHAVE replicates may exist (from `steppedValueSet` on `RAND_SEED` in the NetLogo experiment). Each `[run number]` value becomes a separate `replicate_idx`:

```
output.csv:
  [run number]=1, [step]=1..365  →  replicate_idx=1, metric="TotalIHbees + TotalForagers", timeseries=[...]
  [run number]=1, [step]=1..365  →  replicate_idx=1, metric="TotalDroneEggs + TotalEggs", timeseries=[...]
  [run number]=2, [step]=1..365  →  replicate_idx=2, metric="TotalIHbees + TotalForagers", timeseries=[...]
  ...
```

## Treatment detection

A run is flagged as **treated** (`treatment_on = true`) when `<MaxNumberApplications>` in user.xml is greater than 0. This is how BeeView pairs treated and untreated runs for the Compare Runs analysis.

## Coordinate transformation

The hive coordinates in user.xml are in a **projected CRS** (typically EPSG:32631 for UTM Zone 31N). The importer automatically transforms them to **WGS84** (longitude/latitude) using `xml_parser.transform_coordinates_to_wgs84()` and stores both the original projected and WGS84 coordinates.

## Batch importing: `import_all_experiments.py`

For typical xPollinator workflows with multiple hives, treatments, and Monte Carlo landscape realisations, use `import_all_experiments.py` to import everything in one command.

### Prerequisites

Place experiment folders in the `experiments/` directory. Each folder must follow the naming convention:

```
experiments/
├── exp1_TaG_hive36_mc00__a1b2c3d4/
│   ├── user.xml
│   └── mcs/X3.../processing/BeeHave/output.csv
├── exp4_TaG_hive36_mc00__e5f6g7h8/
│   ├── user.xml
│   └── mcs/X3.../processing/BeeHave/
│       ├── output.csv
│       └── applications.txt          ← treated runs have this file
├── exp1_TaG_hive36_mc01__i9j0k1l2/
│   ...
└── ...
```

Naming pattern: `exp{N}_{scenario}_hive{HH}_mc{MM}__{uuid}`

- `exp1` = untreated, `exp4` = treated (determined by `<MaxNumberApplications>` in user.xml)
- `hive{HH}` = hive location identifier
- `mc{MM}` = Monte Carlo landscape index
- `__{uuid}` = unique run identifier (ignored by the importer)

### Usage

```bash
# Clean import (wipe DB, reimport everything)
python import_all_experiments.py --clean

# Force-replace individual runs that already exist
python import_all_experiments.py --force

# Verbose logging
python import_all_experiments.py --clean -v
```

### How it works

1. Scans `experiments/` for folders matching the naming pattern
2. Groups folders by (hive, scenario, treatment)
3. For each folder, calls the same import logic as `import_run.py`
4. Generates clean `sim_id` values like `hive36_treated_MC0`, `hive36_untreated_MC1`
5. Stores run metadata and bee population replicates in DuckDB
6. Parses `applications.txt` and stores application rows in DuckDB (`applications` table)

### Output

After importing 5 hives × 2 treatments × 10 MC runs = 100 database records:

```
$ python import_all_experiments.py --clean
Cleaned database: deleted all existing runs
Found 100 experiment folders in experiments/
Grouped into 10 batches (hive × treatment):
  hive36_treated   — 10 MC runs
  hive36_untreated — 10 MC runs
  hive37_treated   — 10 MC runs
  ...
Imported 100 runs successfully.
```

### Applications resolution

When `import_all_experiments.py` runs, treated-run application rows are imported into the database.

At runtime, API queries use DB rows first. Legacy fallback still supports file lookup from:

```
source_path/mcs/<mc_folder_name>/processing/BeeHave/applications.txt
```

This means deployed systems can run from `data/beeview.duckdb` without shipping the full `experiments/` tree.

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| `user.xml not found` | Wrong folder path | Point to the `run/<SimID>/` folder, not to `run/<SimID>/mcs/` |
| `No X3* MC folders found` | Run hasn't completed | Check that `mcs/X3*/processing/BeeHave/output.csv` exists |
| `Run already imported` | Duplicate SimID | Use `--force` to replace, or delete existing runs first |
| `Metric unavailable in CSV` | Old BEEHAVE format | Warning only — derived metrics are computed from raw columns when available |
| `replicate count mismatch` | user.xml disagrees with CSV | Warning only — actual CSV count is used |
| No applications on map | Treated run not selected | Select a treated run via View chips — applications are resolved per-run |
| `applications.txt not found` | Missing from experiment folder | Ensure `mcs/<MC>/processing/BeeHave/applications.txt` exists in treated experiment folders |
