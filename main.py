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
from load_pollen import load_pollen_to_db
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
    # Remove all existing entries for debugging
    session.execute(text("DELETE FROM features"))
    session.execute(text("DELETE FROM nectar"))
    session.execute(text("DELETE FROM pollen"))
    session.commit()
    load_shapefile_to_db(SHAPEFILE_PATH, session, 100000)
    load_nectar_to_db(NECTAR_PATH, session)
    load_pollen_to_db(NECTAR_PATH, session)
    session.close()

@app.get("/geojson")
def get_geojson():
    session = next(get_session())
    try:
        result = session.execute(text("SELECT id, name, lulc_label, geometry FROM features"))
        features = []
        for row in result:
            geom = wkt.loads(row.geometry)
            geom = geom.simplify(0.1, preserve_topology=True)
            geojson_geom = mapping(geom)
            features.append({
                "id": row.id,
                "properties": {"name": row.name, "L1_label": row.lulc_label},
                "geometry": geojson_geom
            })
        return JSONResponse(content={"type": "FeatureCollection", "features": features})
    finally:
        session.close()

@app.get("/geojson/viewport")
def get_geojson_viewport(
    min_lng: float,
    min_lat: float, 
    max_lng: float,
    max_lat: float,
    zoom: float = 10.0,
    simplify_tolerance: float = None,
    disable_simplify: bool = False
):
    """
    Get GeoJSON features within the specified viewport bounding box.
    
    Args:
        min_lng: Minimum longitude (west bound)
        min_lat: Minimum latitude (south bound)
        max_lng: Maximum longitude (east bound)
        max_lat: Maximum latitude (north bound)
        zoom: Current zoom level for geometry simplification
        simplify_tolerance: Optional geometry simplification tolerance
    """
    session = next(get_session())
    try:
        # Calculate simplification tolerance based on zoom level if not provided
        if disable_simplify:
            simplify_tolerance = 0  # Disable simplification completely
        elif simplify_tolerance is None:
            # Disable simplification for testing
            simplify_tolerance = 0.01  # Set to 0 to disable
            # Original formula (comment out for testing):
            # simplify_tolerance = max(0.0001, 0.01 / (zoom + 1))
        
        # Create bounding box polygon for intersection query
        bbox_wkt = f"POLYGON(({min_lng} {min_lat}, {max_lng} {min_lat}, {max_lng} {max_lat}, {min_lng} {max_lat}, {min_lng} {min_lat}))"
        
        # DuckDB may not have full spatial functions, so we'll do bounding box filtering in Python
        # First get all features (we'll optimize this with spatial indexing later)
        query = text("SELECT id, name, lulc_label, geometry FROM features")
        result = session.execute(query)
        
        features = []
        bbox_polygon = Polygon([
            (min_lng, min_lat), (max_lng, min_lat), 
            (max_lng, max_lat), (min_lng, max_lat), 
            (min_lng, min_lat)
        ])
        
        for row in result:
            try:
                geom = wkt.loads(row.geometry)
                
                # Check if geometry intersects with bounding box
                if geom.intersects(bbox_polygon):
                    # Simplify geometry based on zoom level
                    if simplify_tolerance > 0:
                        geom = geom.simplify(simplify_tolerance, preserve_topology=True)
                    
                    geojson_geom = mapping(geom)
                    features.append({
                        "id": row.id,
                        "properties": {"name": row.name, "L1_label": row.lulc_label},
                        "geometry": geojson_geom
                    })
            except Exception as e:
                # Skip invalid geometries
                print(f"Error processing geometry for feature {row.id}: {e}")
                continue
        
        return JSONResponse(content={
            "type": "FeatureCollection", 
            "features": features,
            "viewport": {
                "bounds": [min_lng, min_lat, max_lng, max_lat],
                "zoom": zoom,
                "simplify_tolerance": simplify_tolerance,
                "feature_count": len(features)
            }
        })
    finally:
        session.close()

@app.get("/nectar/max")
def get_nectar_max():
    session = next(get_session())
    try:
        result = session.execute(text("SELECT feature_id, timeseries FROM nectar"))
        max_vals = []
        for row in result:
            timeseries = pickle.loads(row.timeseries)
            max_val = np.nan_to_num(timeseries, nan=0).max()
            max_vals.append({"feature_id": row.feature_id, "max_nectar": float(max_val)})
        return {"max_nectar": max_vals}
    finally:
        session.close()

@app.get("/nectar/max/viewport")
def get_nectar_max_viewport(
    min_lng: float,
    min_lat: float, 
    max_lng: float,
    max_lat: float
):
    """Get nectar max values for features within the viewport."""
    session = next(get_session())
    try:
        # Get features in viewport first
        query = text("SELECT id, geometry FROM features")
        result = session.execute(query)
        
        bbox_polygon = Polygon([
            (min_lng, min_lat), (max_lng, min_lat), 
            (max_lng, max_lat), (min_lng, max_lat), 
            (min_lng, min_lat)
        ])
        
        viewport_feature_ids = []
        for row in result:
            try:
                geom = wkt.loads(row.geometry)
                if geom.intersects(bbox_polygon):
                    viewport_feature_ids.append(row.id)
            except Exception:
                continue
        
        if not viewport_feature_ids:
            return {"max_nectar": []}
        
        # Get nectar data for viewport features
        feature_ids_str = ','.join(map(str, viewport_feature_ids))
        nectar_query = text(f"SELECT feature_id, timeseries FROM nectar WHERE feature_id IN ({feature_ids_str})")
        nectar_result = session.execute(nectar_query)
        
        max_vals = []
        for row in nectar_result:
            timeseries = pickle.loads(row.timeseries)
            max_val = np.nan_to_num(timeseries, nan=0).max()
            max_vals.append({"feature_id": row.feature_id, "max_nectar": float(max_val)})
        
        return {"max_nectar": max_vals}
    finally:
        session.close()

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
    try:
        result = session.execute(text(f"SELECT timeseries FROM nectar WHERE feature_id = {int(feature_id)}"))
        nectar_obj = result.fetchone()
        if nectar_obj is None:
            raise HTTPException(status_code=404, detail="Feature ID not found or no nectar data")
        timeseries = pickle.loads(nectar_obj[0])
        # Replace NaN and infinite values with 0.0
        timeseries_clean = np.nan_to_num(timeseries, nan=0.0, posinf=0.0, neginf=0.0)
        return {"feature_id": feature_id, "nectar_timeseries": timeseries_clean.tolist()}
    finally:
        session.close()

@app.get("/pollen/max")
def get_pollen_max():
    session = next(get_session())
    try:
        result = session.execute(text("SELECT feature_id, timeseries FROM pollen"))
        max_vals = []
        for row in result:
            timeseries = pickle.loads(row.timeseries)
            max_val = np.nan_to_num(timeseries, nan=0).max()
            max_vals.append({"feature_id": row.feature_id, "max_pollen": float(max_val)})
        return {"max_pollen": max_vals}
    finally:
        session.close()

@app.get("/pollen/max/viewport")
def get_pollen_max_viewport(
    min_lng: float,
    min_lat: float, 
    max_lng: float,
    max_lat: float
):
    """Get pollen max values for features within the viewport."""
    session = next(get_session())
    try:
        # Get features in viewport first
        query = text("SELECT id, geometry FROM features")
        result = session.execute(query)
        
        bbox_polygon = Polygon([
            (min_lng, min_lat), (max_lng, min_lat), 
            (max_lng, max_lat), (min_lng, max_lat), 
            (min_lng, min_lat)
        ])
        
        viewport_feature_ids = []
        for row in result:
            try:
                geom = wkt.loads(row.geometry)
                if geom.intersects(bbox_polygon):
                    viewport_feature_ids.append(row.id)
            except Exception:
                continue
        
        if not viewport_feature_ids:
            return {"max_pollen": []}
        
        # Get pollen data for viewport features
        feature_ids_str = ','.join(map(str, viewport_feature_ids))
        pollen_query = text(f"SELECT feature_id, timeseries FROM pollen WHERE feature_id IN ({feature_ids_str})")
        pollen_result = session.execute(pollen_query)
        
        max_vals = []
        for row in pollen_result:
            timeseries = pickle.loads(row.timeseries)
            max_val = np.nan_to_num(timeseries, nan=0).max()
            max_vals.append({"feature_id": row.feature_id, "max_pollen": float(max_val)})
        
        return {"max_pollen": max_vals}
    finally:
        session.close()

@app.get("/pollen/timeseries/{feature_id}")
def get_pollen_timeseries(feature_id: str):
    session = next(get_session())
    try:
        result = session.execute(text(f"SELECT timeseries FROM pollen WHERE feature_id = {int(feature_id)}"))
        pollen_obj = result.fetchone()
        if pollen_obj is None:
            raise HTTPException(status_code=404, detail="Feature ID not found or no pollen data")
        timeseries = pickle.loads(pollen_obj[0])
        timeseries_clean = np.nan_to_num(timeseries, nan=0.0, posinf=0.0, neginf=0.0)
        return {"feature_id": feature_id, "pollen_timeseries": timeseries_clean.tolist()}
    finally:
        session.close()

@app.get("/pollen/stream")
def stream_pollen():
    def gen():
        with h5py.File(NECTAR_PATH.replace('nectar', 'pollen'), "r") as f:
            pollen = f["BeeForage/Pollen"]
            for row in pollen:
                yield json.dumps({"max": float(row.max())}) + "\n"
    return StreamingResponse(gen(), media_type="application/json")
