# BeeView Server

This is the backend server for the BeeView application, built with FastAPI.

## Setup Instructions

### Prerequisites

- Python 3.8 or higher
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

The server requires the following data files to be present in the `data/` directory for full functionality:

- **Shapefile for land use/land cover data**:
  - `lulc.shp` (main shapefile)
  - `lulc.dbf` (attribute data)
  - `lulc.prj` (projection information)
  - `lulc.shx` (shape index)
  - `lulc.cpg` (character encoding, optional)

- **Nectar and pollen data**:
  - `arr.dat` (HDF5 file containing nectar and pollen timeseries data)

- **Bee population data**:
  - `output.csv` (CSV file with bee population information)

- **Vegetation mapping**:
  - `vegetation classes.json` (JSON file defining vegetation classes)
  - `land cover to vegetation default mapping.csv` (CSV mapping land cover to vegetation types)

- **Additional files**:
  - `applications.txt` (application-specific data, if needed)

The server will create a DuckDB database file (`beeview.duckdb`) in the `data/` directory on first run or when using `manage_db.py` to reload data.

### API Endpoints

The server provides various endpoints for bee population, nectar, pollen, and vegetation data. Refer to the FastAPI documentation at `http://localhost:32000/docs` for detailed API documentation.