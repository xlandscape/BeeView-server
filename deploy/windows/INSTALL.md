# Installing BeeView and xPollinator on a Windows server

This guide installs the BeeView web application together with the xPollinator landscape model on one
Windows server. Users open BeeView in a browser, inspect the imported simulation runs (forage maps, colony
dynamics, pesticide exposure) and can start new simulations, which run on the server.

The installation has no user authentication. Everyone who can reach the server on the chosen port can
view the data and start simulations. Restrict access with the network firewall of the site (or a
reverse proxy) if that is not acceptable.

## 1. Requirements

| Item | Requirement |
|---|---|
| Operating system | Windows Server 2019 or 2022, or Windows 10/11 (64-bit) |
| Account | Local administrator for the installation |
| CPU and memory | 8 or more cores and 16 GB RAM recommended; a simulation keeps several cores busy for 15 to 60 minutes |
| Disk | 10 GB for the installation, plus about 0.8 GB per simulation (10 Monte Carlo runs) |
| Network | Inbound TCP on the BeeView port (default 32000) from the users' networks |
| Internet | Not needed if the package contains `wheels.zip`; otherwise access to pypi.org once during installation |

No separate Python, Java or NetLogo installation is needed: xPollinator brings Python 3.9.7, a Java
runtime (JDK 24) and NetLogo 5.3.1.

## 2. Contents of the package

| File | Content |
|---|---|
| `xpollinator.zip` | xPollinator model with the xLandscape core, the BEEHAVEecotox component and the Tarn-et-Garonne scenario |
| `beeview-server.zip` | BeeView server (Python, FastAPI) including the built web frontend |
| `data.zip` | BeeView database with all imported simulation runs, the forage array, the land-use map and caches |
| `wheels.zip` | Python packages for an installation without internet access |
| `install.ps1` | Installation and update script |
| `VERSIONS.txt` | Repository, branch and commit of every component in this package |
| `INSTALL.md` | This guide |

## 3. Installation

1. Copy all files of the package into one folder on the server, for example `D:\beeview-package`.
2. Open PowerShell as administrator and change into that folder.
3. Run:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\install.ps1
   ```

4. Wait until the script prints `BeeView-server healthy: True`. The first installation takes about
   5 to 10 minutes, mostly for unpacking xPollinator and installing the Python packages.
5. Open `http://<server name>:32000/` in a browser on a client machine.

The script:

- unpacks xPollinator to `C:\xLandscape\xPollinator` and BeeView-server to `C:\xLandscape\BeeView-server`,
- installs the database from `data.zip` to `C:\xLandscape\BeeView-server\data`,
- creates a Python environment in `C:\xLandscape\BeeView-server\venv` from the bundled Python,
- opens the port in the Windows firewall (rule `BeeView 32000`),
- registers the scheduled task `BeeViewServer`, which starts BeeView at system startup as SYSTEM and
  restarts it after a failure,
- writes logs to `C:\xLandscape\logs`.

### Options

| Option | Default | Meaning |
|---|---|---|
| `-Root <folder>` | `C:\xLandscape` | Installation folder |
| `-Port <number>` | `32000` | Port of the web application |
| `-MaxConcurrentJobs <n>` | `2` | Simulations that run at the same time; further ones wait in a queue |
| `-NoService` | off | No scheduled task and no firewall rule; start BeeView by hand with `C:\xLandscape\run-beeview.cmd` |
| `-ReplaceData` | off | Replace an existing database with the one in `data.zip` (see section 5) |
| `-Source <folder>` | script folder | Folder that holds the package files |

## 4. Operation

| Task | Command (elevated PowerShell) |
|---|---|
| Stop BeeView | `Stop-ScheduledTask BeeViewServer`, then `Get-Process python \| Where-Object Path -like 'C:\xLandscape\BeeView-server\*' \| Stop-Process` |
| Start BeeView | `Start-ScheduledTask BeeViewServer` |
| Check status | open `http://localhost:32000/api/runs` on the server |
| Server log | `C:\xLandscape\logs\beeview-server.log` |
| Simulation results | `C:\xLandscape\xPollinator\run\<simulation id>` |

Simulations started from BeeView run in the background on the server. When a simulation finishes, BeeView
imports its results into the database automatically.

## 5. Database

### What the database contains

`data.zip` holds `beeview.duckdb`, a DuckDB database (DuckDB 1.3.2, pinned in `requirements.txt`) with:

- every imported simulation run: parameters, colony time series of all replicates, pesticide applications,
- the land-use parcels of the scenario with their vegetation class and area,
- the daily nectar and pollen availability of every parcel (shown on the map).

The database is self-contained: BeeView reads all charts and maps from it and does not need the original
simulation folders. The runs therefore do not have to be repeated on the server. Next to the database,
`data/` holds the forage array `arr.dat`, the land-use shapefile and a geometry cache.

The package lists the database content when it is built (number of runs, applications and parcels);
the same numbers can be checked on the server with `http://localhost:32000/api/runs`.

### First installation

`install.ps1` installs the database from `data.zip` automatically when no database exists yet.

### Replacing the database with a newer export

On the source machine, build a new package (see section 7), then on the server:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -ReplaceData
```

The previous data folder is kept as `C:\xLandscape\BeeView_data_backup_<timestamp>`. Runs that were
simulated on the server and are not part of the new export are then missing from BeeView. Their result
folders stay in `C:\xLandscape\xPollinator\run`, and they can be imported again (next section).

### Importing individual runs

A simulation folder (from the server itself or copied from another machine into
`C:\xLandscape\xPollinator\run`) is imported with BeeView stopped:

```powershell
cd C:\xLandscape\BeeView-server
.\venv\Scripts\python.exe import_run.py C:\xLandscape\xPollinator\run\<simulation id>
```

`--force` replaces a run that is already in the database. Start BeeView again afterwards.

### Backup

DuckDB keeps the database file locked while BeeView runs. Stop BeeView, copy
`C:\xLandscape\BeeView-server\data` and `C:\xLandscape\xPollinator\run` to the backup location, and start
BeeView again. A copy of `data` alone is enough to restore the BeeView view of all runs.

## 6. Updating the software

Copy a new package to the server and run `install.ps1` again (without `-ReplaceData`). The script stops
BeeView, replaces the program files, keeps the database, the simulation results and the Python
environment, and starts BeeView again.

## 7. Building the package (source machine)

On the development machine, with all repositories on the branches listed in `VERSIONS.txt` and the local
BeeView server stopped:

```bash
cd BeeView-server
bash deploy/package.sh
```

The package is written to `../_deploy/package/`. Only committed content is packaged; the script warns
about uncommitted or unpushed changes. `WITH_WHEELS=0` skips `wheels.zip`. Behind a TLS-inspecting proxy
set `PIP_CERT` to the CA bundle for the wheel download.

## 8. Troubleshooting

| Symptom | Cause and remedy |
|---|---|
| `pip install failed` | No internet access and no `wheels.zip`: build the package with wheels, or allow access to pypi.org |
| `BeeView-server healthy: False` | See `C:\xLandscape\logs\beeview-server.log`. A port already in use shows as `error while attempting to bind`; choose another `-Port` |
| Browser cannot connect from a client | Check the firewall rule `BeeView 32000` and the site firewall between client and server |
| A simulation fails | See `C:\xLandscape\xPollinator\run\<simulation id>\log\experiment.log` and the `mc_*.log` files next to it |
| Database errors after copying `data` by hand | The file was copied while BeeView was running. Stop BeeView and copy again, or install with `-ReplaceData` |

## 9. Known limitations of the current data

The simulation runs in this database were computed before a fix in the xLandscape core (1.19.1) and in
the BEEHAVEecotox component: maize, sorghum and hazelnut fields did not provide pollen to the simulated
colonies. The forage map already shows the corrected pollen of these crops, and new simulations started on
the server use the corrected model. The imported runs will be replaced after they have been recomputed.
