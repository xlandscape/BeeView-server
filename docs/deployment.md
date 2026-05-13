# Deployment

This page covers practical deployment workflows for BeeView-server on Windows and Unix/Linux.

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
