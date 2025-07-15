from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import h5py
import json
import numpy as np
import geopandas as gpd
from shapely.geometry import shape, mapping, MultiPolygon, Polygon

app = FastAPI()

# Load once at startup
with open("server/data/Tarn_LULC_v04.geojson") as f:
    GEOJSON_DATA = json.load(f)

# Helper: Map feature id to index
FEATURE_ID_TO_INDEX = {
    str(feature["id"]): idx
    for idx, feature in enumerate(GEOJSON_DATA["features"])
}

# Allow all origins (for development)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Or specify ["http://localhost:3000"] etc.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/geojson")
def get_geojson():
    return JSONResponse(content=GEOJSON_DATA)

# def safe_shape(feature):
#     try:
#         return shape(feature["geometry"])
#     except Exception as e:
#         print(f"Skipping feature {feature.get('id', '')}: {e}")
#         return None

# def is_valid_polygon(geom):
#     # Check for empty, invalid, or non-numeric coordinates
#     if geom is None or not isinstance(geom, Polygon):
#         return False
#     if geom.is_empty or not geom.is_valid:
#         return False
#     # Check for NaN or None in coordinates
#     coords = np.array(geom.exterior.coords)
#     if np.isnan(coords).any() or np.isinf(coords).any():
#         return False
#     return True

# @app.get("/geojson/dissolved")
# def get_dissolved_geojson():
#     valid_features = []
#     for feature in GEOJSON_DATA["features"]:
#         geom = safe_shape(feature)
#         if is_valid_polygon(geom):
#             props = feature.get("properties", {})
#             valid_features.append({"geometry": MultiPolygon([geom]), **props})
#         else:
#             print(f"Invalid or skipped geometry for feature id: {feature.get('id', '')}")

#     if not valid_features:
#         raise HTTPException(status_code=500, detail="No valid polygons found.")

#     gdf = gpd.GeoDataFrame(valid_features, geometry="geometry")
#     dissolved = gdf.dissolve(by="L1_label", as_index=False)
#     dissolved_geojson = dissolved.__geo_interface__
#     return JSONResponse(content=dissolved_geojson)

@app.get("/nectar/max")
def get_nectar_max():
    with h5py.File("server/data/arr.dat", "r") as f:
        nectar = f["BeeForage/Nectar"][:]
        max_vals = np.nan_to_num(nectar, nan=0).max(axis=1).tolist()
    return {"max_nectar": max_vals}

@app.get("/nectar/stream")
def stream_nectar():
    def gen():
        with h5py.File("server/data/arr.dat", "r") as f:
            nectar = f["BeeForage/Nectar"]
            for row in nectar:
                yield json.dumps({"max": float(row.max())}) + "\n"
    return StreamingResponse(gen(), media_type="application/json")

@app.get("/nectar/timeseries/{feature_id}")
def get_nectar_timeseries(feature_id: str):
    idx = FEATURE_ID_TO_INDEX.get(str(feature_id))
    if idx is None:
        raise HTTPException(status_code=404, detail="Feature ID not found")
    with h5py.File("server/data/arr.dat", "r") as f:
        nectar = np.nan_to_num(f["BeeForage/Nectar"][idx, :], nan=0).tolist()
    return {"feature_id": feature_id, "nectar_timeseries": nectar}