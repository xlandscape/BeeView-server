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

The complete installation and operation guide for the target machine, including the database
export, is `deploy/windows/INSTALL.md`; it is shipped with every package.

### Build the package (source machine)

Stop the local BeeView server first (DuckDB holds an exclusive lock on `data/beeview.duckdb`), then:

```bash
bash deploy/package.sh
```

The script packages the committed state of xPollinator (with the core and BeeHaveEcotox submodules and
the Tarn-et-Garonne scenario), BeeView-server and a fresh BeeView frontend build, plus a checkpointed copy
of the database and offline Python wheels, into `../_deploy/package/`: `xpollinator.zip`,
`beeview-server.zip`, `data.zip`, `wheels.zip`, `install.ps1`, `INSTALL.md` and `VERSIONS.txt` (branch and
commit of every repository). `deploy/aws/deploy.sh package` calls the same script.

### Install, update, database

See `deploy/windows/INSTALL.md`: `install.ps1` installs or updates; `-ReplaceData` swaps in the database
of a newer package; single runs are imported with `import_run.py`.

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
