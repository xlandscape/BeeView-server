# Deployment

This page covers practical deployment workflows for BeeView-server on Windows and Unix/Linux.

## Windows Server (full stack, no authentication)

Use this for a Windows server that should run simulations as well as serve BeeView (for example a
university server). It reuses the artefacts and the install logic of the AWS deployment
(`deploy/aws/`) but needs no AWS account, no load balancer and no identity provider. The server is
reachable without authentication by everyone who can reach the machine on the chosen port, so rely
on the network firewall of the site.

No separate Python installation is needed: the BeeView-server virtual environment is created from
the Python 3.9.7 bundled with xPollinator (`model/core/bin/python-3.9.7-amd64`). The server code is
kept compatible with Python 3.9 for this reason (no `X | Y` type annotations outside modules with
`from __future__ import annotations`).

### Build the artefacts (source machine)

Stop the local BeeView server first (DuckDB holds an exclusive lock on `data/beeview.duckdb`), then:

```bash
bash deploy/aws/deploy.sh package
```

This writes to `../_deploy/`:

- `xpollinator.zip` (about 1.3 GB: model, bundled Python, JDK, NetLogo, scenarios, scripts)
- `beeview-server.zip` (server code and built `frontend/`)
- `data.zip` (`beeview.duckdb`, geometry and forage caches, shapefile, `arr.dat`, csv)
- `install.ps1` (copy of `deploy/windows/install.ps1`)

Copy the four files to the target machine (USB, network share, SCP).

### Install on the target machine

In an elevated PowerShell, from the folder holding the files:

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

Options: `-Root C:\xLandscape` (install location), `-Port 32000`, `-MaxConcurrentJobs 2`,
`-NoService` (no scheduled task; start by hand with `C:\xLandscape\run-beeview.cmd`).

The script extracts the archives to `C:\xLandscape\xPollinator` and `C:\xLandscape\BeeView-server`,
creates the venv and installs `requirements.txt` from PyPI (internet access needed once; behind a
TLS-inspecting proxy set `PIP_CERT` to the CA bundle), opens the Windows firewall port, registers
the scheduled task `BeeViewServer` (runs as SYSTEM at startup, restarts on failure) and waits until
`http://localhost:<Port>/api/runs` answers. Logs are in `C:\xLandscape\logs\`.

### Update

Build new artefacts, copy them over, run `install.ps1` again. It stops the service, replaces the
code, and keeps `xPollinator\run` (simulation results), `BeeView-server\data` (database and caches)
and the venv. To replace the database as well, delete `C:\xLandscape\BeeView-server\data` before
the run; `data.zip` is then extracted again.

### Backup

There is no snapshot mechanism on a plain server. Back up `C:\xLandscape\BeeView-server\data` and
`C:\xLandscape\xPollinator\run` with the site's regular backup, with the service stopped
(`Stop-ScheduledTask BeeViewServer`) when copying `beeview.duckdb`.

## Windows Deployment (Portable / xcopy)

Use this when you want to hand over a ready-to-run folder to another Windows operator with minimal setup.

### What is included

The portable bundle contains:

- Server code (`*.py`)
- Prebuilt frontend (`frontend/`)
- Data files (`data/beeview.duckdb`, `data/arr.dat`, `data/lulc.*`, vegetation mapping files)
- Helper scripts (`setup.bat`, `start.bat`)

Applications are stored in DuckDB, so `experiments/` is not required for runtime.

### Build the portable bundle (on source machine)

From `BeeView-server/`:

```bat
package.bat
```

This creates `BeeView-portable/`.

### Deploy on target Windows machine

1. Copy `BeeView-portable/` to the target machine.
2. Install Python 3.11+ and ensure it is on `PATH`.
3. Open Command Prompt in `BeeView-portable/`.
4. Run:

```bat
setup.bat
start.bat
```

The app is served from one endpoint: [http://localhost:32000](http://localhost:32000)

### Operational notes

- First run creates a local virtual environment (`venv/`) and installs dependencies.
- `start.bat` opens the browser automatically.
- To stop the server, press `Ctrl+C` in the terminal window.

## Reusing an Existing DuckDB File

If you already have a populated `beeview.duckdb`, you can deploy with that file directly and skip re-importing runs.

### Windows

1. Copy your existing DB to:

```bat
BeeView-portable\data\beeview.duckdb
```

2. If a DB already exists in the target folder, replace it while the server is stopped.
3. Start normally:

```bat
setup.bat
start.bat
```

### Unix/Linux

1. Copy your existing DB to:

```bash
cp /path/to/beeview.duckdb /opt/BeeView-server/data/beeview.duckdb
```

2. Ensure server process is stopped before replacing the file.
3. Start the service/app again (`python main.py`, `uvicorn`, or `systemctl start beeview-server`).

### Compatibility checks

The DB should include current BeeView-server tables (`runs`, `bee_population_replicate`, `applications`, plus landscape tables).

Quick verification after startup:

1. `GET /api/runs` returns run records.
2. `GET /api/applications?run_id=<treated_id>` returns application rows.
3. Frontend loads at `/` without triggering re-import workflows.

If schema mismatches occur (older DB), rebuild by importing runs again with current scripts.

## Unix/Linux Build and Deployment

Use this when deploying to Linux hosts, VMs, or lab servers.

### Prerequisites

- Python 3.11+
- Node.js 18+ and npm (for frontend build)

### Build steps (source machine or CI)

1. Build frontend assets:

```bash
cd BeeView
npm ci
npm run build
```

2. Copy frontend build output to BeeView-server:

```bash
cd ../BeeView-server
rm -rf frontend
cp -r ../BeeView/dist frontend
```

3. Prepare runtime environment:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

4. Ensure required data exists under `data/`:

- `beeview.duckdb` (preferred, pre-populated)
- `arr.dat`
- `lulc.shp`, `lulc.dbf`, `lulc.prj`, `lulc.shx` (and optionally `lulc.cpg`)
- `vegetation classes.json`
- `land cover to vegetation default mapping.csv`

### Run in foreground

```bash
source venv/bin/activate
python main.py
```

Open [http://localhost:32000](http://localhost:32000).

### Run with uvicorn (recommended for Unix services)

```bash
source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 32000
```

For dev autoreload:

```bash
uvicorn main:app --reload --port 32000
```

### Minimal systemd example (Linux)

```ini
[Unit]
Description=BeeView-server
After=network.target

[Service]
WorkingDirectory=/opt/BeeView-server
ExecStart=/opt/BeeView-server/venv/bin/uvicorn main:app --host 0.0.0.0 --port 32000
Restart=always
User=beeview
Group=beeview
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable beeview-server
sudo systemctl start beeview-server
sudo systemctl status beeview-server
```

## Verification Checklist

After deployment, verify:

1. API docs: [http://localhost:32000/docs](http://localhost:32000/docs)
2. Runs endpoint: [http://localhost:32000/api/runs](http://localhost:32000/api/runs)
3. Frontend root: [http://localhost:32000](http://localhost:32000)
4. Applications endpoint with treated run id: `/api/applications?run_id=<treated_id>`
