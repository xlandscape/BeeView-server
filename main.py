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
from database import get_session, engine
from models import Feature, Nectar, Pollen, BeePopulation, LandCoverVegetationMapping, Base
from load_shapefile import load_shapefile_to_db
from load_nectar import load_nectar_to_db
from load_pollen import load_pollen_to_db
from load_bee_population import load_bee_population_to_db
from load_vegetation_mapping import load_vegetation_mapping
from xml_parser import get_beehive_location, get_beehive_buffer_bounds
import pickle
import logging

# Configure logging once at application startup
logging.basicConfig(level=logging.WARNING)

# Set specific loggers
logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
logging.getLogger('sqlalchemy.dialects').setLevel(logging.WARNING)
logging.getLogger('load_shapefile').setLevel(logging.INFO)  # If you want load_shapefile logs

app = FastAPI()

SHAPEFILE_PATH = os.getenv("SHAPEFILE_PATH", "data/Tarn_LULC_v04.shp")
NECTAR_PATH = os.getenv("NECTAR_PATH", "data/arr.dat")
BEE_POPULATION_PATH = os.getenv("BEE_POPULATION_PATH", "data/output.csv")
VEGETATION_MAPPING_PATH = os.getenv("VEGETATION_MAPPING_PATH", "data/land cover to vegetation default mapping.csv")
# Configurable radius around beehive location (in kilometers)
BEEHIVE_RADIUS_KM = float(os.getenv("BEEHIVE_RADIUS_KM", "5.0"))

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
    
    # Ensure tables exist
    Base.metadata.create_all(engine)
    
    print("DATA LOADING: Loading fresh data...")
    print(f"Using beehive radius filter: {BEEHIVE_RADIUS_KM}km")
    load_vegetation_mapping(VEGETATION_MAPPING_PATH)
    load_shapefile_to_db(SHAPEFILE_PATH, session, 30000, BEEHIVE_RADIUS_KM)
    load_nectar_to_db(NECTAR_PATH, session)
    load_pollen_to_db(NECTAR_PATH, session)
    load_bee_population_to_db(BEE_POPULATION_PATH, session)
    session.close()
    print("SERVER STARTUP: Server startup complete!")

@app.on_event("shutdown")
def shutdown_event():
    print("SERVER SHUTDOWN: Server shutting down...")

@app.get("/api/features/all")
def get_all_feature_ids():
    """Get all feature IDs"""
    session = next(get_session())
    try:
        result = session.execute(text("SELECT DISTINCT id FROM features ORDER BY id"))
        feature_ids = [row[0] for row in result.fetchall()]
        return {"feature_ids": feature_ids}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()

@app.get("/api/beehive-location")
def api_get_beehive_location():
    """Get the beehive location from template.xrun"""
    try:
        location = get_beehive_location()
        if location:
            return location
        else:
            raise HTTPException(status_code=404, detail="Beehive location not found in template.xrun")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading beehive location: {str(e)}")

@app.get("/api/beehive-radius")
def get_beehive_radius():
    """Get the current beehive radius configuration"""
    return {
        "radius_km": BEEHIVE_RADIUS_KM,
        "description": "Current radius filter around beehive location"
    }

@app.get("/api/beehive-buffer")
def get_beehive_buffer():
    """Get the beehive buffer area bounds"""
    try:
        bounds = get_beehive_buffer_bounds(BEEHIVE_RADIUS_KM)
        if bounds:
            return bounds
        else:
            raise HTTPException(status_code=404, detail="Could not calculate beehive buffer")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error calculating beehive buffer: {str(e)}")

@app.get("/api/vegetation-mapping")
def get_vegetation_mapping():
    """Get all vegetation mapping data"""
    session = next(get_session())
    try:
        result = session.execute(text("SELECT * FROM land_cover_vegetation_mapping"))
        mappings = []
        for row in result:
            mappings.append({
                "id": row.id,
                "l1_code": row.l1_code,
                "l1_label": row.l1_label,
                "l2_code": row.l2_code,
                "l2_label": row.l2_label,
                "l3_code": row.l3_code,
                "l3_label": row.l3_label,
                "vegetation": row.vegetation
            })
        return {"mappings": mappings}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()

@app.get("/api/vegetation-codes-map")
def get_vegetation_codes_map():
    """Get vegetation mapping as a dictionary keyed by L1_code-L2_code-L3_code"""
    session = next(get_session())
    try:
        result = session.execute(text("SELECT l1_code, l2_code, l3_code, vegetation FROM land_cover_vegetation_mapping"))
        mapping_dict = {}
        for row in result:
            key = f"{row.l1_code}-{row.l2_code}-{row.l3_code}"
            mapping_dict[key] = row.vegetation
        return {"mapping": mapping_dict}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()

@app.get("/api/vegetation/{l1_code}/{l2_code}/{l3_code}")
def get_vegetation_for_codes(l1_code: int, l2_code: int, l3_code: int):
    """Get vegetation type for specific L1, L2, L3 codes combination"""
    session = next(get_session())
    try:
        result = session.execute(
            text("SELECT vegetation FROM land_cover_vegetation_mapping WHERE l1_code = :l1 AND l2_code = :l2 AND l3_code = :l3"),
            {"l1": l1_code, "l2": l2_code, "l3": l3_code}
        )
        row = result.fetchone()
        if row:
            return {"l1_code": l1_code, "l2_code": l2_code, "l3_code": l3_code, "vegetation": row.vegetation}
        else:
            raise HTTPException(status_code=404, detail=f"No vegetation mapping found for codes: {l1_code}/{l2_code}/{l3_code}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()

@app.get("/geojson")
def get_geojson():
    session = next(get_session())
    try:
        result = session.execute(text("SELECT id, name, l1_code, l1_label, l2_code, l2_label, l3_code, l3_label, geometry FROM features"))
        features = []
        for row in result:
            geom = wkt.loads(row.geometry)
            # geom = geom.simplify(0.1, preserve_topology=True)
            geojson_geom = mapping(geom)
            features.append({
                "id": row.id,
                "properties": {
                    "name": row.name, 
                    "L1_code": row.l1_code,
                    "L1_label": row.l1_label,
                    "L2_code": row.l2_code,
                    "L2_label": row.l2_label,
                    "L3_code": row.l3_code,
                    "L3_label": row.l3_label
                },
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
    disable_simplify: bool = True
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
            simplify_tolerance = 0  # Set to 0 to disable
            # Original formula (comment out for testing):
            # simplify_tolerance = max(0.0001, 0.01 / (zoom + 1))
        
        # Create bounding box polygon for intersection query
        bbox_wkt = f"POLYGON(({min_lng} {min_lat}, {max_lng} {min_lat}, {max_lng} {max_lat}, {min_lng} {max_lat}, {min_lng} {min_lat}))"
        
        # DuckDB may not have full spatial functions, so we'll do bounding box filtering in Python
        # First get all features (we'll optimize this with spatial indexing later)
        query = text("SELECT id, name, l1_code, l1_label, l2_code, l2_label, l3_code, l3_label, geometry FROM features")
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
                        "properties": {
                            "name": row.name, 
                            "L1_code": row.l1_code,
                            "L1_label": row.l1_label,
                            "L2_code": row.l2_code,
                            "L2_label": row.l2_label,
                            "L3_code": row.l3_code,
                            "L3_label": row.l3_label
                        },
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

# New time-specific endpoints for time point selection
@app.get("/api/nectar/timeseries")
def get_nectar_timeseries_data():
    """Get aggregate nectar time series data for the time series chart."""
    session = next(get_session())
    try:
        # Get sample timeseries data for visualization
        result = session.execute(text("SELECT feature_id, timeseries FROM nectar LIMIT 10"))
        timeseries_data = []
        
        # Mock dates for demonstration (replace with actual date logic from your data)
        dates = [f"2023-{month:02d}-01" for month in range(1, 13)]
        
        for row in result:
            timeseries = pickle.loads(row.timeseries)
            timeseries_clean = np.nan_to_num(timeseries, nan=0.0)
            
            # Sample the timeseries to match date points
            sample_indices = np.linspace(0, len(timeseries_clean)-1, len(dates), dtype=int)
            
            for i, date in enumerate(dates):
                if i < len(sample_indices):
                    concentration = float(timeseries_clean[sample_indices[i]])
                    timeseries_data.append({
                        "date": date,
                        "nectar_species": f"Species_{row.feature_id % 5}",  # Group features into species
                        "nectar_concentration": concentration
                    })
        
        return timeseries_data
    finally:
        session.close()

@app.get("/api/nectar/viewport-timeseries")
def get_nectar_viewport_timeseries():
    """Get viewport-specific nectar time series data."""
    # For now, return the same data as full timeseries
    # In a real implementation, you'd use viewport parameters
    return get_nectar_timeseries_data()

@app.get("/api/nectar/time-point/{date}")
def get_nectar_for_time_point(date: str):
    """Get nectar values for all features at a specific time point."""
    session = next(get_session())
    try:
        result = session.execute(text("SELECT feature_id, timeseries FROM nectar"))
        time_point_data = []
        
        # Convert date to time index
        try:
            # First try to parse as day-of-year integer (1-365)
            time_index = int(date) - 1  # Convert to 0-based index
            if time_index < 0 or time_index >= 365:
                time_index = 0
        except ValueError:
            # If not an integer, try parsing as date string
            try:
                from datetime import datetime
                date_obj = datetime.strptime(date, '%Y-%m-%d')
                time_index = date_obj.timetuple().tm_yday - 1
            except:
                time_index = 0
        
        for row in result:
            timeseries = pickle.loads(row.timeseries)
            timeseries_clean = np.nan_to_num(timeseries, nan=0.0)
            
            # Get value at specific time point
            if time_index < len(timeseries_clean):
                concentration = float(timeseries_clean[time_index])
            else:
                concentration = 0.0
                
            time_point_data.append({
                "feature_id": row.feature_id,
                "nectar_concentration": concentration,
                "date": date
            })
        
        return {"nectar_data": time_point_data, "date": date}
    finally:
        session.close()

@app.get("/api/nectar/time-point/{date}/viewport")
def get_nectar_for_time_point_viewport(
    date: str,
    min_lng: float,
    min_lat: float, 
    max_lng: float,
    max_lat: float
):
    """Get nectar values for viewport features at a specific time point."""
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
            return {"nectar_data": [], "date": date}
        
        # Map date to time index
        try:
            # First try to parse as day-of-year integer (1-365)
            time_index = int(date) - 1  # Convert to 0-based index
            if time_index < 0 or time_index >= 365:
                time_index = 0
        except ValueError:
            # If not an integer, try parsing as date string
            try:
                from datetime import datetime
                date_obj = datetime.strptime(date, '%Y-%m-%d')
                time_index = date_obj.timetuple().tm_yday - 1
            except:
                time_index = 0
        
        # Get nectar data for viewport features
        feature_ids_str = ','.join(map(str, viewport_feature_ids))
        nectar_query = text(f"SELECT feature_id, timeseries FROM nectar WHERE feature_id IN ({feature_ids_str})")
        nectar_result = session.execute(nectar_query)
        
        time_point_data = []
        for row in nectar_result:
            timeseries = pickle.loads(row.timeseries)
            timeseries_clean = np.nan_to_num(timeseries, nan=0.0)
            
            if time_index < len(timeseries_clean):
                concentration = float(timeseries_clean[time_index])
            else:
                concentration = 0.0
                
            time_point_data.append({
                "feature_id": row.feature_id,
                "nectar_concentration": concentration,
                "date": date
            })
        
        return {"nectar_data": time_point_data, "date": date}
    finally:
        session.close()

@app.get("/api/pollen/time-point/{date}")
def get_pollen_for_time_point(date: str):
    """Get pollen values for all features at a specific time point."""
    session = next(get_session())
    try:
        result = session.execute(text("SELECT feature_id, timeseries FROM pollen"))
        time_point_data = []
        
        # Convert date to time index
        try:
            # First try to parse as day-of-year integer (1-365)
            time_index = int(date) - 1  # Convert to 0-based index
            if time_index < 0 or time_index >= 365:
                time_index = 0
        except ValueError:
            # If not an integer, try parsing as date string
            try:
                from datetime import datetime
                date_obj = datetime.strptime(date, '%Y-%m-%d')
                time_index = date_obj.timetuple().tm_yday - 1
            except:
                time_index = 0
        
        for row in result:
            timeseries = pickle.loads(row.timeseries)
            timeseries_clean = np.nan_to_num(timeseries, nan=0.0)
            
            if time_index < len(timeseries_clean):
                concentration = float(timeseries_clean[time_index])
            else:
                concentration = 0.0
                
            time_point_data.append({
                "feature_id": row.feature_id,
                "pollen_concentration": concentration,
                "date": date
            })
        
        return {"pollen_data": time_point_data, "date": date}
    finally:
        session.close()

@app.get("/api/pollen/time-point/{date}/viewport")
def get_pollen_for_time_point_viewport(
    date: str,
    min_lng: float,
    min_lat: float, 
    max_lng: float,
    max_lat: float
):
    """Get pollen values for viewport features at a specific time point."""
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
            return {"pollen_data": [], "date": date}
        
        try:
            from datetime import datetime
            date_obj = datetime.strptime(date, '%Y-%m-%d')
            time_index = date_obj.timetuple().tm_yday - 1
        except:
            time_index = 0
        
        feature_ids_str = ','.join(map(str, viewport_feature_ids))
        pollen_query = text(f"SELECT feature_id, timeseries FROM pollen WHERE feature_id IN ({feature_ids_str})")
        pollen_result = session.execute(pollen_query)
        
        time_point_data = []
        for row in pollen_result:
            timeseries = pickle.loads(row.timeseries)
            timeseries_clean = np.nan_to_num(timeseries, nan=0.0)
            
            if time_index < len(timeseries_clean):
                concentration = float(timeseries_clean[time_index])
            else:
                concentration = 0.0
                
            time_point_data.append({
                "feature_id": row.feature_id,
                "pollen_concentration": concentration,
                "date": date
            })
        
        return {"pollen_data": time_point_data, "date": date}
    finally:
        session.close()


@app.get("/api/timeseries/averages")
def get_timeseries_averages(feature_ids: str = None, include_nectar: bool = True, include_pollen: bool = True):
    """Get average nectar and pollen values for selected features across all days.
    If no feature_ids provided, returns average across ALL features."""
    session = next(get_session())
    try:
        # Parse feature_ids from comma-separated string if provided
        if feature_ids:
            feature_ids_list = [int(id.strip()) for id in feature_ids.split(',') if id.strip()]
            use_all_features = False
        else:
            feature_ids_list = []
            use_all_features = True
        
        
        if not feature_ids_list and not use_all_features:
            return {"averages": []}
        
        # Collect all timeseries data with optimized queries
        nectar_timeseries = []
        pollen_timeseries = []
        
        if include_nectar:
            # Single query to get all nectar timeseries
            if use_all_features:
                nectar_query = text("SELECT timeseries FROM nectar")
            else:
                feature_ids_str = ','.join(map(str, feature_ids_list))
                nectar_query = text(f"SELECT timeseries FROM nectar WHERE feature_id IN ({feature_ids_str})")
            
            nectar_result = session.execute(nectar_query)
            for row in nectar_result:
                timeseries = pickle.loads(row.timeseries)
                timeseries_clean = np.nan_to_num(timeseries, nan=0.0)
                nectar_timeseries.append(timeseries_clean)
        
        if include_pollen:
            # Single query to get all pollen timeseries
            if use_all_features:
                pollen_query = text("SELECT timeseries FROM pollen")
            else:
                feature_ids_str = ','.join(map(str, feature_ids_list))
                pollen_query = text(f"SELECT timeseries FROM pollen WHERE feature_id IN ({feature_ids_str})")
            
            pollen_result = session.execute(pollen_query)
            for row in pollen_result:
                timeseries = pickle.loads(row.timeseries)
                timeseries_clean = np.nan_to_num(timeseries, nan=0.0)
                pollen_timeseries.append(timeseries_clean)
        
        # Convert to numpy arrays for efficient computation
        if nectar_timeseries:
            nectar_array = np.array(nectar_timeseries)
            # Ensure all timeseries have the same length (365 days)
            min_length = min(len(ts) for ts in nectar_timeseries)
            nectar_array = nectar_array[:, :min(min_length, 365)]
        
        if pollen_timeseries:
            pollen_array = np.array(pollen_timeseries)
            min_length = min(len(ts) for ts in pollen_timeseries)
            pollen_array = pollen_array[:, :min(min_length, 365)]
        
        # Compute daily averages for all days at once
        daily_averages = []
        max_days = 365
        
        if nectar_timeseries:
            max_days = min(max_days, nectar_array.shape[1])
        if pollen_timeseries:
            max_days = min(max_days, pollen_array.shape[1])
        
        for day in range(max_days):
            day_data = {"day": day + 1}  # Convert to 1-based day numbering
            
            if include_nectar and nectar_timeseries:
                # Compute average across all features for this day
                day_data["nectar_avg"] = float(np.mean(nectar_array[:, day]))
            else:
                day_data["nectar_avg"] = 0.0
            
            if include_pollen and pollen_timeseries:
                # Compute average across all features for this day
                day_data["pollen_avg"] = float(np.mean(pollen_array[:, day]))
            else:
                day_data["pollen_avg"] = 0.0
            
            daily_averages.append(day_data)
        
        # Ensure we always return 365 days
        while len(daily_averages) < 365:
            day_data = {
                "day": len(daily_averages) + 1,
                "nectar_avg": 0.0,
                "pollen_avg": 0.0
            }
            daily_averages.append(day_data)
        
        return {"averages": daily_averages}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()

# Bee Population endpoints
@app.get("/api/bee-population/time-point/{day}")
def get_bee_population_for_day(day: int):
    """Get bee population data for a specific day"""
    if day < 1 or day > 365:
        raise HTTPException(status_code=400, detail="Day must be between 1 and 365")
    
    session = next(get_session())
    try:
        records = session.query(BeePopulation).all()
        
        if not records:
            raise HTTPException(status_code=404, detail="No bee population data found")
        
        result = {"day": day}
        for record in records:
            timeseries = pickle.loads(record.timeseries)
            time_index = day - 1  # Convert to 0-based index
            if time_index < len(timeseries):
                result[record.metric_name] = float(timeseries[time_index])
            else:
                result[record.metric_name] = 0.0
        
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()

@app.get("/api/bee-population/timeseries")
def get_bee_population_timeseries():
    """Get complete time series for all bee population metrics"""
    session = next(get_session())
    try:
        # Get all metrics
        records = session.query(BeePopulation).all()
        
        data = {}
        for record in records:
            timeseries = pickle.loads(record.timeseries)
            data[record.metric_name] = timeseries.tolist()
        
        # Create day-by-day structure
        if data:
            num_days = len(next(iter(data.values())))
            result = []
            for day in range(num_days):
                day_data = {"day": day + 1}  # Days 1-365
                for metric, values in data.items():
                    day_data[metric] = values[day] if day < len(values) else 0.0
                result.append(day_data)
            
            return {"timeseries": result}
        
        return {"timeseries": []}
        
    finally:
        session.close()

@app.get("/api/bee-population/metrics")
def get_bee_population_metrics():
    """Get list of available bee population metrics"""
    session = next(get_session())
    try:
        result = session.query(BeePopulation.metric_name).distinct().all()
        metrics = [row.metric_name for row in result]
        return {"metrics": metrics}
    finally:
        session.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
