# Installation

## Prerequisites

- **Python 3.10+** (tested with 3.11)
- Access to xPollinator simulation outputs (see [Data Requirements](data-requirements.md))

## Setting up the environment

### 1. Create a virtual environment

```bash
cd BeeView-server
python -m venv venv
```

### 2. Activate it

=== "Windows (cmd)"

    ```bat
    venv\Scripts\activate
    ```

=== "Windows (PowerShell)"

    ```powershell
    venv\Scripts\Activate.ps1
    ```

=== "Linux / macOS"

    ```bash
    source venv/bin/activate
    ```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

If you are behind a corporate proxy or VPN that intercepts SSL certificates, install `pip-system-certs` first:

```bash
pip install --trusted-host pypi.org --trusted-host pypi.python.org --trusted-host files.pythonhosted.org pip-system-certs
pip install -r requirements.txt
```

### Key dependencies

| Package | Purpose |
|---------|---------|
| `fastapi` + `uvicorn` | Web server and API framework |
| `duckdb` + `duckdb-engine` | Embedded analytical database |
| `sqlalchemy` | ORM for database access |
| `h5py` | Reading HDF5 data stores (`arr.dat`) |
| `geopandas` + `shapely` + `fiona` | Shapefile loading and geometry operations |
| `numpy` + `pandas` | Numerical data processing |
| `pyproj` | Coordinate reference system transformations |

## Starting the server

Three options are available:

### Option 1: Interactive management (recommended)

```bash
python manage_db.py
```

Presents a menu to delete/reset the database, start the server, or inspect database contents.

### Option 2: Direct start

```bash
python main.py
```

Starts the server on port 32000. On first run, creates the database and loads landscape data from `data/`.

### Option 3: Uvicorn with auto-reload (development)

```bash
python -m uvicorn main:app --reload --port 32000
```

Useful during development — the server restarts automatically when Python files change.

## Verifying the installation

Once the server is running, open:

- **API docs**: [http://localhost:32000/docs](http://localhost:32000/docs) — interactive Swagger UI
- **Health check**: [http://localhost:32000/api/features/all](http://localhost:32000/api/features/all) — should return a list of feature IDs

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `SHAPEFILE_PATH` | `data/lulc.shp` | Path to the LULC shapefile |
| `NECTAR_PATH` | `data/arr.dat` | Path to the HDF5 data store |
| `BEE_POPULATION_PATH` | `data/output.csv` | Path to the legacy BEEHAVE output CSV |
| `VEGETATION_CLASSES_PATH` | `data/vegetation classes.json` | Path to vegetation class definitions |
| `BEEHIVE_RADIUS_KM` | `30.0` | Radius filter around beehive (km) |
| `SKIP_LEGACY_DATA_LOADING` | *(unset)* | Set to `1` to start with an empty database |
