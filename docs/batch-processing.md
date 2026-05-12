# Batch Processing

When running experiments with multiple hive locations and Monte Carlo realisations, xPollinator produces many individual run folders. BeeView-server includes helper scripts to consolidate these folders and import them in bulk.

## Experiment folder structure

A typical multi-hive experiment produces individual run folders like:

```
experiments/
├── exp4_TaG_hive36_mc0__6a702c44-.../   ← hive 36, MC 0
├── exp4_TaG_hive36_mc1__8800af6e-.../   ← hive 36, MC 1
├── exp4_TaG_hive36_mc2__7d003aae-.../   ← hive 36, MC 2
├── ...
├── exp4_TaG_hive76_mc0__8bb88bde-.../   ← hive 76, MC 0
├── exp4_TaG_hive76_mc1__b5e639f9-.../   ← hive 76, MC 1
└── ...
```

Each folder contains one MC realisation for one hive location. To import these into BeeView, they need to be consolidated into the structure that `import_run.py` expects.

## Consolidation with `process_exp4.py`

The `process_exp4.py` script reorganises individual MC folders into the consolidated structure:

```bash
python process_exp4.py
```

This scans the `experiments/` directory for folders matching the pattern `exp4_<base>_hive<HH>_mc<MM>__<uuid>` and groups them by hive:

**Before** (individual MC folders):
```
experiments/
├── exp4_TaG_hive36_mc0__6a702c44-.../
├── exp4_TaG_hive36_mc1__8800af6e-.../
└── exp4_TaG_hive36_mc2__7d003aae-.../
```

**After** (consolidated per-hive folder):
```
experiments/
└── exp4_TaG_hive36/
    ├── user.xml       ← copied from any MC folder
    └── mcs/
        ├── X3.../     ← symlink or copy of mc0's MC folder
        ├── X3.../     ← mc1
        └── X3.../     ← mc2
```

The consolidated folder matches the structure expected by `import_run.py`.

## Updating hive metadata with `update_hives.py`

The `update_hives.py` script updates `user.xml` files in experiment folders — for example, to normalise `<SimID>` values across a batch:

```bash
python update_hives.py
```

This scans `experiments/` for folders matching `exp1_TaG_hive<HH>` and rewrites the `<SimID>` in each `user.xml` to a standardised format (e.g. `hive36` instead of the original long identifier).

!!! note
    This script is specific to the exp1 naming convention. Adapt the regex pattern for different experiment prefixes.

## Batch import workflow

The recommended workflow for importing a multi-hive experiment:

### Step 1: Consolidate MC folders

```bash
python process_exp4.py
```

### Step 2: Reset the database (if starting fresh)

```bash
python manage_db.py
# Choose option 1: Delete database and start server (empty DB)
# Then Ctrl+C to stop the server
```

### Step 3: Import each hive

```bash
# Untreated runs
python import_run.py experiments/exp1_TaG_hive36 --force
python import_run.py experiments/exp1_TaG_hive37 --force
python import_run.py experiments/exp1_TaG_hive52 --force

# Treated runs
python import_run.py experiments/exp4_TaG_hive36 --force
python import_run.py experiments/exp4_TaG_hive37 --force
python import_run.py experiments/exp4_TaG_hive52 --force
```

Or import all at once with a loop:

=== "Bash"

    ```bash
    for dir in experiments/exp1_TaG_hive*/; do
        python import_run.py "$dir" --force
    done
    for dir in experiments/exp4_TaG_hive*/; do
        python import_run.py "$dir" --force
    done
    ```

=== "PowerShell"

    ```powershell
    Get-ChildItem experiments/exp1_TaG_hive* -Directory | ForEach-Object {
        python import_run.py $_.FullName --force
    }
    Get-ChildItem experiments/exp4_TaG_hive* -Directory | ForEach-Object {
        python import_run.py $_.FullName --force
    }
    ```

### Step 4: Start the server

```bash
python manage_db.py
# Choose option 2: Start server as-is
```

### Step 5: Verify in BeeView

Open BeeView and check that all imported hive locations appear as chips in the header bar.

## Naming conventions

For BeeView's Compare Runs feature to work correctly, treated and untreated runs must be **paired**. Pairing relies on:

- **`hive_group_id`** — must be identical between treated and untreated runs at the same hive location (e.g. `hive36`). Set via `<HiveGroupId>` in the `.xrun` file.
- **`outer_mc_id`** — must match between paired runs (same landscape realisation index).

The `<SimID>` typically follows the pattern `hive<HH>_treated` or `hive<HH>_untreated`. The importer strips `_treated`/`_untreated` suffixes to derive `hive_group_id` when `<HiveGroupId>` is not explicitly set.
