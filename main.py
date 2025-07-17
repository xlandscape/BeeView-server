from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import h5py
import json
import numpy as np
import geopandas as gpd
from shapely.geometry import shape, mapping, MultiPolygon, Polygon
from shapely import wkt
import os
from sqlalchemy import text
from database import get_session
from models import Feature, Nectar
from load_shapefile import load_shapefile_to_db
from load_nectar import load_nectar_to_db
import pickle

app = FastAPI()

SHAPEFILE_PATH = os.getenv("SHAPEFILE_PATH", "data/Tarn_LULC_v04.shp")
NECTAR_PATH = os.getenv("NECTAR_PATH", "data/arr.dat")

# Allow all origins (for development)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Or specify ["http://localhost:3000"] etc.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup_event():
    session = next(get_session())
    count = session.execute(text("SELECT COUNT(*) FROM features")).scalar()
    if count == 0:
        load_shapefile_to_db(SHAPEFILE_PATH, session, 100)
    nectar_count = session.execute(text("SELECT COUNT(*) FROM nectar")).scalar()
    if nectar_count == 0:
        load_nectar_to_db(NECTAR_PATH, session)

@app.get("/geojson")
def get_geojson():
    session = next(get_session())
    # Select a random subset of 1000 rows
    result = session.execute(text("SELECT id, name, lulc_label, geometry FROM features"))
    features = []
    for row in result:
        # Convert WKT to GeoJSON geometry
        geom = wkt.loads(row.geometry)
        geojson_geom = mapping(geom)
        features.append({
            "id": row.id,
            "properties": {"name": row.name, "L1_label": row.lulc_label},
            "geometry": geojson_geom
        })
    return JSONResponse(content={"type": "FeatureCollection", "features": features})

@app.get("/nectar/max")
def get_nectar_max():
    session = next(get_session())
    result = session.execute(text("SELECT feature_id, timeseries FROM nectar"))
    max_vals = []
    for row in result:
        timeseries = pickle.loads(row.timeseries)
        max_val = np.nan_to_num(timeseries, nan=0).max()
        max_vals.append({"feature_id": row.feature_id, "max_nectar": float(max_val)})
    return {"max_nectar": max_vals}

@app.get("/nectar/stream")
def stream_nectar():
    def gen():
        with h5py.File(NECTAR_PATH, "r") as f:
            nectar = f["BeeForage/Nectar"]
            for row in nectar:
                yield json.dumps({"max": float(row.max())}) + "\n"
    return StreamingResponse(gen(), media_type="application/json")

@app.get("/nectar/timeseries/{feature_id}")
def get_nectar_timeseries(feature_id: str):
    session = next(get_session())
    result = session.execute(text(f"SELECT timeseries FROM nectar WHERE feature_id = {int(feature_id)}"))
    nectar_obj = result.fetchone()
    if nectar_obj is None:
        raise HTTPException(status_code=404, detail="Feature ID not found or no nectar data")
    timeseries = pickle.loads(nectar_obj[0])
    return {"feature_id": feature_id, "nectar_timeseries": timeseries.tolist()}