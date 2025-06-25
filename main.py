from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import h5py
import json
import numpy as np

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