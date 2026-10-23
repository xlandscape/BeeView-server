# Setting up BeeView with xPollinator from source

This page describes how to assemble a working BeeView system from the git repositories: which
repositories and branches to check out, where they have to sit relative to each other, which runtimes
are needed, and how to bring over an existing database so that simulations do not have to be repeated.

BeeView-server is the integration point of the system. It serves the BeeView web frontend, reads and
writes the BeeView database, and starts xPollinator simulations. This page therefore lives here.

## 1. Components

| Repository | Role | Depends on |
|---|---|---|
| [xPollinator](https://github.com/xlandscape/xPollinator) | Landscape model (simulations); contains the model core and the BEEHAVEecotox component as git submodules | Java runtime (download, section 3) |
| [LandscapeModel-Core](https://github.com/xlandscape/LandscapeModel-Core) | xLandscape framework core, submodule `xPollinator/model/core`; includes Python 3.9.7 for Windows | — |
| [BeeHaveEcotox-Component](https://github.com/xlandscape/BeeHaveEcotox-Component) | BEEHAVEecotox coupling, submodule `xPollinator/model/variant/BeeHaveEcotox`; includes NetLogo 5.3.1 | Java runtime |
| [Scenario-TarnEtGaronne](https://github.com/xlandscape/Scenario-TarnEtGaronne) | Landscape scenario used by the BeeView runs; a separate clone inside `xPollinator/scenario/` (not a submodule) | — |
| [BeeView-server](https://github.com/xlandscape/BeeView-server) | Backend (FastAPI, DuckDB); serves the frontend, imports runs, starts simulations | xPollinator, built BeeView frontend |
| [BeeView](https://github.com/xlandscape/BeeView) | Web frontend (React, MapLibre, deck.gl); built once and copied into BeeView-server | Node.js (build only) |

## 2. Branches

The current state is spread over feature branches whose pull requests are not merged yet. Use:

| Repository | Branch | Notes |
|---|---|---|
| xPollinator | `feature/core-1.19.1` | Pins core to master `6f468280` (1.19.0 + hotfix 1.19.1) and BeeHaveEcotox to `bugfix/pollen-only-patches` |
| LandscapeModel-Core | (via submodule) | master `6f468280`; the 1.19.1 tag is not set yet |
| BeeHaveEcotox-Component | (via submodule) | `bugfix/pollen-only-patches` (`10fa611`) |
| Scenario-TarnEtGaronne | `feature/sunshine-hours` | Adds `weather/sunshine_hours.txt`, the default foraging hours of the scenario |
| BeeView-server | `feature/entomology-demo` | Contains the core 1.19 parameter changes and the Python 3.9 compatibility |
| BeeView | `feature/entomology-demo` | Colony KPIs, Monte Carlo bands, side-by-side comparison, parcel popup |

Once the pull requests are merged, all repositories move back to `develop`, and the xPollinator
submodule pointers then select the matching core and BeeHaveEcotox commits.

The two BeeView branches belong together: the frontend of `feature/entomology-demo` calls endpoints that
only the server branch of the same name provides.

## 3. Runtimes and tools

| Dependency | Version | Needed for | Source |
|---|---|---|---|
| Windows | 10, 11, Server 2019 or 2022, 64-bit | everything (the bundled Python and Java are Windows builds) | — |
| Git | any recent version | checkout | <https://git-scm.com> |
| Python for xPollinator | 3.9.7 | simulations | bundled in the core: `xPollinator/model/core/bin/python-3.9.7-amd64` |
| Java | JDK 24 | NetLogo / BEEHAVEecotox | <https://xlandscape.org/releases/jdk-24-v1.0.zip>, extract into `xPollinator/model/variant/BeeHaveEcotox` so that `jdk-24/bin/java.exe` exists (not in git) |
| NetLogo | 5.3.1 | BEEHAVEecotox | included in BeeHaveEcotox-Component |
| Python for BeeView-server | 3.9 to 3.11 | backend | the bundled 3.9.7 works (no separate installation), or a python.org installation |
| Python packages | `BeeView-server/requirements.txt` (DuckDB pinned to 1.3.2) | backend | PyPI |
| Node.js and npm | Node 18 or newer (tested with 22.15) | building the frontend only; not needed at runtime | <https://nodejs.org> |

Hardware: a simulation keeps several cores busy for 15 to 60 minutes and writes about 0.8 GB per
simulation with 10 Monte Carlo runs. 8 or more cores, 16 GB RAM and 20 GB free disk are a sensible
minimum.

## 4. Checkout

xPollinator and BeeView-server must be siblings: BeeView-server finds the model at `../xPollinator`
unless `XPOLLINATOR_PATH` says otherwise.

```bat
mkdir C:\xLandscape
cd C:\xLandscape

git clone -b feature/core-1.19.1 --recurse-submodules https://github.com/xlandscape/xPollinator.git
git clone -b feature/sunshine-hours https://github.com/xlandscape/Scenario-TarnEtGaronne.git xPollinator\scenario\Scenario-TarnEtGaronne
git clone -b feature/entomology-demo https://github.com/xlandscape/BeeView-server.git
git clone -b feature/entomology-demo https://github.com/xlandscape/BeeView.git
```

Then extract the Java runtime: download `jdk-24-v1.0.zip` and unpack it into
`C:\xLandscape\xPollinator\model\variant\BeeHaveEcotox`. Check that
`C:\xLandscape\xPollinator\model\variant\BeeHaveEcotox\jdk-24\bin\java.exe` exists.

Resulting layout:

```
C:\xLandscape
├── xPollinator
│   ├── model\core                       (submodule, includes Python 3.9.7)
│   ├── model\variant\BeeHaveEcotox      (submodule, includes NetLogo; add jdk-24 here)
│   └── scenario\Scenario-TarnEtGaronne  (separate clone)
├── BeeView-server
└── BeeView
```

The clone of xPollinator with submodules is about 1.7 GB, mostly the Python runtime in the core.

## 5. Build the frontend

```bat
cd C:\xLandscape\BeeView
npm install
npm run build
xcopy /E /I /Y dist ..\BeeView-server\frontend
```

`frontend\` is not tracked in BeeView-server; repeat these steps whenever BeeView changes. Behind a
TLS-inspecting proxy, point `NODE_EXTRA_CA_CERTS` at the proxy's CA bundle before `npm install`. BeeView has no committed `package-lock.json`, so the installed package versions follow the ranges in `package.json`.

## 6. Python environment of BeeView-server

With the Python bundled in xPollinator:

```bat
cd C:\xLandscape\BeeView-server
..\xPollinator\model\core\bin\python-3.9.7-amd64\python.exe -m venv venv
venv\Scripts\python.exe -m pip install --upgrade pip
venv\Scripts\python.exe -m pip install -r requirements.txt
```

A python.org Python 3.10 or 3.11 works the same way (`py -3.11 -m venv venv`). Behind a TLS-inspecting
proxy, set `PIP_CERT` to the proxy's CA bundle.

## 7. Database: bring over the existing runs

BeeView keeps everything it displays in a DuckDB database: the parameters and colony time series of every
imported run, pesticide applications, land-use parcels, and daily nectar and pollen per parcel. The
database is self-contained. Copying it transfers all runs; the simulation folders are not needed to view
them.

On the source machine, stop BeeView-server (DuckDB locks the file while the server runs) and copy these
files from `BeeView-server\data` to `C:\xLandscape\BeeView-server\data` on the target:

| File | Purpose |
|---|---|
| `beeview.duckdb` | the database |
| `Tarn_LULC_v04.shp`, `.shx`, `.dbf`, `.prj`, `.cpg` | land-use map; the importer reads the coordinate system of new runs from the `.prj`. Identical to `xPollinator\scenario\Scenario-TarnEtGaronne\geo\Tarn_LULC_v04.*`, so it can be copied from there instead |
| `arr.dat` | forage array of the scenario (only used when a database is rebuilt from files) |
| `cache\landscape_*.pkl` | optional geometry cache; rebuilt automatically when missing |

If the source server was not shut down cleanly, a `beeview.duckdb.wal` file sits next to the database;
copy it as well (DuckDB applies it at the next start).

`vegetation classes.json` and `land cover to vegetation default mapping.csv` are part of the repository.

The database file format matches DuckDB 1.3.2, the version pinned in `requirements.txt`. Use the same
version on both machines.

To add runs later, copy the run folder into `C:\xLandscape\xPollinator\run` and import it with
BeeView-server stopped:

```bat
cd C:\xLandscape\BeeView-server
venv\Scripts\python.exe import_run.py ..\xPollinator\run\<SimID>
```

`--force` replaces a run with the same SimID. Simulations started from BeeView are imported
automatically when they finish.

Building a database from scratch, without an existing `beeview.duckdb`, is not covered here.

## 8. Start and check

```bat
cd C:\xLandscape\BeeView-server
set XPOLLINATOR_PATH=C:\xLandscape\xPollinator
venv\Scripts\python.exe main.py
```

Open <http://localhost:32000/>. The server log shows `DATABASE: Using existing database with 25211
features` when the copied database was found.

| Variable | Default | Meaning |
|---|---|---|
| `XPOLLINATOR_PATH` | `../xPollinator` | xPollinator checkout used for simulations |
| `BEEVIEW_PORT` | `32000` | HTTP port |
| `MAX_CONCURRENT_JOBS` | `1` | simulations that run at the same time; further ones wait in a queue |

Checks:

1. `http://localhost:32000/api/runs` lists the imported runs.
2. The map shows the land use; with the Pollen layer on and the day slider in July or August, maize
   fields carry pollen and no nectar.
3. A test simulation of the model alone, from `C:\xLandscape\xPollinator`:

   ```bat
   model\core\bin\python-3.9.7-amd64\python.exe -u model\core\init.py template.xrun
   ```

   It creates `run\TestRun`; delete that folder before running it again (SimIDs must be unique).
   `scripts\check_xrun.py <file.xrun>` lists parameters a `.xrun` file lacks.

## 9. Running as a service

BeeView-server has no authentication; restrict access with the firewall. To start it at boot, register
a scheduled task that runs `main.py` as above at system startup; `deploy/windows/install.ps1` shows a
complete example (scheduled task `BeeViewServer`, firewall rule, restart on failure).

## 10. Known limitations

- The 240 runs in the current database were simulated before the core 1.19.1 and BeeHaveEcotox fixes:
  maize, sorghum and hazelnut did not provide pollen to the simulated colonies. The forage map in the
  database already shows the corrected values. New simulations use the corrected model; the 240 runs will
  be recomputed.
- Core 1.19 requires the `.xrun` parameters `ExperimentID` and `LandscapeScenario` in addition to `SimID`
  and `Project`. BeeView-server and `scripts/run_batch.py` write both; older `.xrun` files are updated
  with `scripts/update_xrun_weather.py`.
