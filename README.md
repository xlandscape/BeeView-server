# BeeView Server

This is the backend server for the BeeView application, built with FastAPI.

## Setup Instructions

### Prerequisites

- Python 3.10 or higher (tested with 3.11)
- pip (Python package installer)

### Installation

1. Navigate to the server directory:
   ```
   cd BeeView-server
   ```

2. Install the required dependencies:
   ```
   pip install -r requirements.txt
   ```

### Running the Server

#### Option 1: Direct Start

To start the development server directly, run:
```
python main.py
```

The server will start on `http://0.0.0.0:32000`.

If `frontend/` exists with a built BeeView app, open `http://localhost:32000` for the UI.

#### Option 2: Using manage_db.py

The `manage_db.py` script is a database management utility that provides an interactive menu for handling the DuckDB database and starting the server. It allows you to:

- Delete the existing database and reload fresh data
- Start the server with the current database (or create one if missing)
- View detailed database information (file size, table record counts)

To use it, run:
```
python manage_db.py
```

Follow the on-screen prompts to select your desired action. The script will handle database operations and server startup automatically.

### Environment Variables

You can configure the following environment variables:

- `SHAPEFILE_PATH`: Path to the shapefile (default: `data/lulc.shp`)
- `NECTAR_PATH`: Path to the nectar data file (default: `data/arr.dat`)
- `BEE_POPULATION_PATH`: Path to the bee population data (default: `data/output.csv`)
- `VEGETATION_CLASSES_PATH`: Path to the vegetation classes JSON (default: `data/vegetation classes.json`)
- `BEEHIVE_RADIUS_KM`: Radius around the beehive location in kilometers (default: `30.0`)

### Data Requirements

The server supports two workflows:

#### Modern workflow (recommended): `import_all_experiments.py`

Import all experiment runs from the `experiments/` folder:

```bash
python import_all_experiments.py --clean
```

This scans `experiments/` for folders matching the pattern `exp{N}_TaG_hive{HH}_mc{MM}__{uuid}`, groups them by hive and treatment, and imports each MC run into the database with clean naming. Flags:

| Flag | Effect |
|------|--------|
| `--clean` | Wipe all existing runs before importing (fresh start) |
| `--force` | Replace individual runs that already exist |
| `-v` | Verbose logging |

After import, the `data/` folder only needs:

- `beeview.duckdb` — the database (auto-created)
- `arr.dat` — HDF5 with nectar/pollen/vegetation timeseries
- `vegetation classes.json` — vegetation class definitions
- Shapefile (`*.shp`, `*.dbf`, `*.prj`, `*.shx`) — land use/land cover polygons

Applications data (`applications.txt`) is imported into DuckDB (`applications` table) by `import_all_experiments.py` and served from the database.

### Deployment Guides

Detailed platform-specific deployment docs are in MkDocs:

- Windows portable/xcopy deployment: `docs/deployment.md`
- Unix/Linux build and deployment: `docs/deployment.md`

Windows helper scripts in this repository:

- `package.bat` — builds a `BeeView-portable/` handover folder
- `setup.bat` — creates `venv` and installs dependencies on target machine
- `start.bat` — launches BeeView-server and opens browser

#### Legacy workflow: file-based startup

Place all data files directly in `data/` and let the server load them on first startup. Required files:

- `lulc.shp` (+ `.dbf`, `.prj`, `.shx`, `.cpg`) — land use shapefile
- `arr.dat` — HDF5 nectar/pollen data
- `output.csv` — BEEHAVE colony output
- `vegetation classes.json` — vegetation class definitions
- `land cover to vegetation default mapping.csv` — LULC to vegetation mapping

The server creates `beeview.duckdb` in `data/` on first start.

### API Endpoints

The server provides various endpoints for bee population, nectar, pollen, and vegetation data. Refer to the FastAPI documentation at `http://localhost:32000/docs` for detailed API documentation.