from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
import h5py
import json
import glob
import numpy as np
import geopandas as gpd
from shapely.geometry import shape, mapping, MultiPolygon, Polygon
from shapely import wkt
import os
from sqlalchemy import text
from database import get_session, engine
from models import (
    Application,
    Base,
    BeePopulation,
    BeePopulationReplicate,
    Feature,
    FeatureIds,
    Nectar,
    Pollen,
    Run,
    Vegetation,
    VegetationClassMapping,
)
from load_shapefile import load_shapefile_to_db
from load_nectar import load_nectar_to_db
from load_pollen import load_pollen_to_db
from load_bee_population import load_bee_population_to_db
from load_feature_ids import load_feature_ids_to_db
from load_vegetation_classes import load_vegetation_classes_to_db
from load_vegetation import load_vegetation_to_db
from xml_parser import get_beehive_location, get_beehive_buffer_bounds
from geometry_cache import cache as geometry_cache
from forage_cache import cache as forage_cache
from compare import (
    compute_ed_matrix,
    compute_exceedance,
    compute_percentiles_pairs,
    compute_percentiles_relative,
    compute_reduction_matrix,
    compute_relative,
    compute_survival_probabilities,
)
import pickle
import logging

# Configure logging once at application startup
logging.basicConfig(level=logging.WARNING)

# Set specific loggers
logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
logging.getLogger('sqlalchemy.dialects').setLevel(logging.WARNING)
logging.getLogger('load_shapefile').setLevel(logging.INFO)
logging.getLogger('load_feature_ids').setLevel(logging.INFO)
logging.getLogger('load_vegetation_classes').setLevel(logging.INFO)
logging.getLogger('load_vegetation').setLevel(logging.INFO)
logging.getLogger('load_nectar').setLevel(logging.INFO)
logging.getLogger('load_pollen').setLevel(logging.INFO)
logging.getLogger('load_bee_population').setLevel(logging.INFO)
logging.getLogger('geometry_cache').setLevel(logging.INFO)
logging.getLogger('forage_cache').setLevel(logging.INFO)
logging.getLogger('load_vegetation_mapping').setLevel(logging.INFO)

# Main app logger
logger = logging.getLogger(__name__)

app = FastAPI()

SHAPEFILE_PATH = os.getenv("SHAPEFILE_PATH", "data/lulc.shp")
NECTAR_PATH = os.getenv("NECTAR_PATH", "data/arr.dat")
BEE_POPULATION_PATH = os.getenv("BEE_POPULATION_PATH", "data/output.csv")
VEGETATION_CLASSES_PATH = os.getenv("VEGETATION_CLASSES_PATH", "data/vegetation classes.json")
# Configurable radius around beehive location (in kilometers)
BEEHIVE_RADIUS_KM = float(os.getenv("BEEHIVE_RADIUS_KM", "30.0"))

# Allow all origins (for development)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Or specify ["http://localhost:3000"] etc.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Compress every JSON/JS/CSS response above 1 KB. /geojson serves a pre-gzipped
# body with Content-Encoding already set, which this middleware passes through.
app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=6)


@app.middleware("http")
async def static_cache_headers(request: Request, call_next):
    """Vite emits content-hashed filenames under /assets, so they can be cached forever."""
    response = await call_next(request)
    if request.url.path.startswith("/assets/") and response.status_code == 200:
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


@app.on_event("startup")
def startup_event():
    _initialize_database()
    # Build the simplified landscape GeoJSON off the request path. Until it is
    # ready, /geojson and /geojson/viewport wait for it (or fall back if it fails).
    geometry_cache.start_background_build()
    forage_cache.start_background_build()


def _initialize_database():
    # Check if database file exists
    db_file_path = "data/beeview.duckdb"
    database_exists = os.path.exists(db_file_path)
    
    session = next(get_session())
    
    # Always ensure tables exist (safe operation)
    Base.metadata.create_all(engine)
    
    if database_exists:
        # Check if database has data
        from sqlalchemy import text
        try:
            result = session.execute(text("SELECT COUNT(*) FROM features"))
            feature_count = result.scalar()
            
            if feature_count > 0:
                logger.info(f"DATABASE: Using existing database with {feature_count} features")
                logger.info("SERVER STARTUP: Server startup complete (using existing data)!")
                session.close()
                return
            else:
                logger.info("DATABASE: Database exists but is empty, loading fresh data...")
        except Exception as e:
            logger.info(f"DATABASE: Database exists but appears corrupted ({e}), loading fresh data...")
    else:
        logger.info("DATABASE: No database found, creating and loading fresh data...")
    
    # Allow callers (e.g. manage_db.py) to start the server with a blank DB
    # without triggering the legacy file-based data loading.
    if os.getenv("SKIP_LEGACY_DATA_LOADING", "").lower() in ("1", "true", "yes"):
        logger.info("DATA LOADING: Skipped (SKIP_LEGACY_DATA_LOADING is set). Use import_run.py to populate the database.")
        session.close()
        return

    # Load fresh data
    logger.info("DATA LOADING: Loading fresh data...")
    logger.info(f"Using beehive radius filter: {BEEHIVE_RADIUS_KM}km")

    try:
        # Load feature IDs from HDF first
        load_feature_ids_to_db(NECTAR_PATH, session)

        # Load vegetation class mapping from JSON
        load_vegetation_classes_to_db(VEGETATION_CLASSES_PATH, session)

        # Load vegetation data from HDF
        load_vegetation_to_db(NECTAR_PATH, session)

        # Load shapefile and map to feature IDs
        load_shapefile_to_db(SHAPEFILE_PATH, session, 30000, BEEHIVE_RADIUS_KM)

        # Load nectar and pollen data
        load_nectar_to_db(NECTAR_PATH, session)
        load_pollen_to_db(NECTAR_PATH, session)

        # Load bee population data
        load_bee_population_to_db(BEE_POPULATION_PATH, session)
        
        logger.info("SERVER STARTUP: Server startup complete (fresh data loaded)!")
    except Exception as e:
        logger.error(f"ERROR: Failed to load data: {e}")
        raise e
    finally:
        session.close()

@app.on_event("shutdown")
def shutdown_event():
    logger.info("SERVER SHUTDOWN: Server shutting down...")

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
    except HTTPException:
        raise
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

@app.get("/api/vegetation-classes")
def get_vegetation_classes():
    """Get all vegetation class mappings"""
    session = next(get_session())
    try:
        result = session.execute(text("SELECT vegetation_name, vegetation_class FROM vegetation_class_mapping"))
        mappings = {}
        for row in result:
            mappings[row.vegetation_name] = row.vegetation_class
        return {"vegetation_classes": mappings}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()

@app.get("/api/vegetation/feature/{feature_id}")
def get_vegetation_for_feature(feature_id: int):
    """Get vegetation class for a specific feature using the new mapping system"""
    session = next(get_session())
    try:
        # Get the index for this feature_id directly (feature_id is now the parameter we receive)
        index_result = session.execute(text("SELECT index FROM feature_ids WHERE feature_id = :fid"), {"fid": feature_id})
        index_row = index_result.fetchone()

        if not index_row:
            raise HTTPException(status_code=404, detail=f"No index found for feature_id {feature_id}")

        feature_index = index_row.index

        # Get the vegetation class for this feature index
        veg_result = session.execute(text("SELECT vegetation_class FROM vegetation WHERE feature_index = :idx"), {"idx": feature_index})
        veg_row = veg_result.fetchone()

        if not veg_row:
            raise HTTPException(status_code=404, detail=f"No vegetation data found for feature index {feature_index}")

        return {
            "feature_id": feature_id,
            "vegetation_class": veg_row.vegetation_class
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()

@app.get("/api/vegetation/class/{vegetation_class}")
def get_vegetation_class_name(vegetation_class: int):
    """Get vegetation name for a specific vegetation class"""
    session = next(get_session())
    try:
        result = session.execute(text("SELECT vegetation_name FROM vegetation_class_mapping WHERE vegetation_class = :vc"), {"vc": vegetation_class})
        row = result.fetchone()
        if row:
            return {"vegetation_class": vegetation_class, "vegetation_name": row.vegetation_name}
        else:
            raise HTTPException(status_code=404, detail=f"No vegetation name found for class: {vegetation_class}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()

@app.get("/api/features/vegetation-mapping")
def get_features_vegetation_mapping():
    """Get vegetation classes for all features"""
    session = next(get_session())
    try:
        query = text("""
            SELECT f.feature_id, v.vegetation_class, vcm.vegetation_name
            FROM features f
            LEFT JOIN feature_ids fi ON f.feature_id = fi.feature_id
            LEFT JOIN vegetation v ON fi.index = v.feature_index
            LEFT JOIN vegetation_class_mapping vcm ON v.vegetation_class = vcm.vegetation_class
            WHERE f.feature_id IS NOT NULL
            ORDER BY f.feature_id
        """)
        result = session.execute(query)

        mappings = []
        for row in result:
            mappings.append({
                "feature_id": row.feature_id,  # Use the actual shapefile feature_id consistently
                "vegetation_class": row.vegetation_class,
                "vegetation_name": row.vegetation_name
            })

        return {"feature_vegetation_mappings": mappings}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()

@app.get("/geojson")
def get_geojson(request: Request):
    """Full landscape as GeoJSON (simplified, precision-rounded, pre-gzipped, ETag-cached)."""
    if geometry_cache.wait_ready(timeout=120):
        headers = {
            "ETag": geometry_cache.etag,
            "Cache-Control": "public, max-age=0, must-revalidate",
            "Vary": "Accept-Encoding",
        }
        if request.headers.get("if-none-match") == geometry_cache.etag:
            return Response(status_code=304, headers=headers)
        if "gzip" in request.headers.get("accept-encoding", ""):
            headers["Content-Encoding"] = "gzip"
            return Response(content=geometry_cache.full_gzip, media_type="application/json", headers=headers)
        return Response(content=geometry_cache.full_bytes, media_type="application/json", headers=headers)

    logger.warning("/geojson: geometry cache unavailable, serving unsimplified geometry from the database")
    return _get_geojson_legacy()


def _get_geojson_legacy():
    session = next(get_session())
    try:
        result = session.execute(text("SELECT id, feature_id, name, l1_code, l1_label, l2_code, l2_label, l3_code, l3_label, area_hectares, geometry FROM features"))
        features = []
        for row in result:
            geom = wkt.loads(row[10])  # geometry is now at index 10
            geojson_geom = mapping(geom)
            features.append({
                "id": row[1],  # feature_id
                "properties": {
                    "name": row[2], 
                    "L1_code": row[3],
                    "L1_label": row[4],
                    "L2_code": row[5],
                    "L2_label": row[6],
                    "L3_code": row[7],
                    "L3_label": row[8],
                    "area_hectares": row[9]
                },
                "geometry": geojson_geom
            })
        return JSONResponse(content={"type": "FeatureCollection", "features": features})
    finally:
        session.close()


@app.get("/api/geojson/cache-status")
def get_geojson_cache_status():
    """Diagnostics for the in-memory landscape GeoJSON cache."""
    return geometry_cache.stats()


# ---------------------------------------------------------------------------
# Forage matrices: whole nectar/pollen tables as compact binary downloads so
# the browser can scrub through the year without further requests.
# ---------------------------------------------------------------------------
@app.get("/api/forage/index")
def get_forage_index():
    """Row order (feature ids) and day count for /api/forage/{kind}.f32."""
    if not forage_cache.wait_ready(timeout=120):
        raise HTTPException(status_code=503, detail="Forage matrices not available")
    return {
        "feature_ids": forage_cache.feature_ids.tolist(),
        "days": forage_cache.n_days,
        "kinds": list(forage_cache.matrix.keys()),
        "etag": forage_cache.etag,
    }


@app.get("/api/forage/{kind}.f32")
def get_forage_matrix(kind: str, request: Request):
    """Row-major little-endian float32 matrix (features x days), pre-gzipped, ETag-cached."""
    if kind not in ("nectar", "pollen"):
        raise HTTPException(status_code=404, detail=f"Unknown forage kind: {kind}")
    if not forage_cache.wait_ready(timeout=120):
        raise HTTPException(status_code=503, detail="Forage matrices not available")
    headers = {
        "ETag": forage_cache.etag,
        "Cache-Control": "public, max-age=0, must-revalidate",
        "Vary": "Accept-Encoding",
        "X-Forage-Rows": str(len(forage_cache.feature_ids)),
        "X-Forage-Days": str(forage_cache.n_days),
    }
    if request.headers.get("if-none-match") == forage_cache.etag:
        return Response(status_code=304, headers=headers)
    if "gzip" in request.headers.get("accept-encoding", ""):
        headers["Content-Encoding"] = "gzip"
        return Response(content=forage_cache.gzip_bytes[kind], media_type="application/octet-stream", headers=headers)
    return Response(content=forage_cache.matrix[kind].tobytes(), media_type="application/octet-stream", headers=headers)


@app.get("/api/forage/cache-status")
def get_forage_cache_status():
    return forage_cache.stats()


def _viewport_feature_ids(min_lng, min_lat, max_lng, max_lat):
    """Feature ids intersecting the bbox, from the geometry cache (None if unavailable)."""
    if geometry_cache.wait_ready(timeout=120):
        return geometry_cache.feature_ids_in_bbox(min_lng, min_lat, max_lng, max_lat)
    return None

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
    if geometry_cache.wait_ready(timeout=120):
        body, _ = geometry_cache.viewport(min_lng, min_lat, max_lng, max_lat)
        return Response(content=body, media_type="application/json")

    logger.warning("/geojson/viewport: geometry cache unavailable, scanning all geometries in the database")
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
        query = text("SELECT id, feature_id, name, l1_code, l1_label, l2_code, l2_label, l3_code, l3_label, area_hectares, geometry FROM features")
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
                        "id": row.feature_id,
                        "properties": {
                            "name": row.name, 
                            "L1_code": row.l1_code,
                            "L1_label": row.l1_label,
                            "L2_code": row.l2_code,
                            "L2_label": row.l2_label,
                            "L3_code": row.l3_code,
                            "L3_label": row.l3_label,
                            "area_hectares": row.area_hectares
                        },
                        "geometry": geojson_geom
                    })
            except Exception as e:
                # Skip invalid geometries
                logger.warning(f"Error processing geometry for feature {row.id}: {e}")
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
    if forage_cache.wait_ready(timeout=120):
        return {"max_nectar": [{"feature_id": f, "max_nectar": v} for f, v in forage_cache.maxima("nectar")]}
    session = next(get_session())
    try:
        result = session.execute(text("""
            SELECT fi.feature_id, n.timeseries 
            FROM nectar n 
            JOIN feature_ids fi ON n.feature_index = fi.index
        """))
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
    ids = _viewport_feature_ids(min_lng, min_lat, max_lng, max_lat)
    if ids is not None and forage_cache.wait_ready(timeout=120):
        return {"max_nectar": [{"feature_id": f, "max_nectar": v} for f, v in forage_cache.maxima("nectar", ids)]}
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
        nectar_query = text(f"""
            SELECT fi.feature_id, n.timeseries 
            FROM nectar n 
            JOIN feature_ids fi ON n.feature_index = fi.index 
            WHERE fi.feature_id IN ({feature_ids_str})
        """)
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
    if forage_cache.wait_ready(timeout=120):
        series = forage_cache.series("nectar", int(feature_id))
        if series is None:
            raise HTTPException(status_code=404, detail="Feature ID not found or no nectar data")
        return {"feature_id": feature_id, "nectar_timeseries": series}
    session = next(get_session())
    try:
        result = session.execute(text("""
            SELECT n.timeseries 
            FROM nectar n 
            JOIN feature_ids fi ON n.feature_index = fi.index 
            WHERE fi.feature_id = :feature_id
        """), {"feature_id": int(feature_id)})
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
    if forage_cache.wait_ready(timeout=120):
        return {"max_pollen": [{"feature_id": f, "max_pollen": v} for f, v in forage_cache.maxima("pollen")]}
    session = next(get_session())
    try:
        result = session.execute(text("""
            SELECT fi.feature_id, p.timeseries 
            FROM pollen p 
            JOIN feature_ids fi ON p.feature_index = fi.index
        """))
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
    ids = _viewport_feature_ids(min_lng, min_lat, max_lng, max_lat)
    if ids is not None and forage_cache.wait_ready(timeout=120):
        return {"max_pollen": [{"feature_id": f, "max_pollen": v} for f, v in forage_cache.maxima("pollen", ids)]}
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
        pollen_query = text(f"""
            SELECT fi.feature_id, p.timeseries 
            FROM pollen p 
            JOIN feature_ids fi ON p.feature_index = fi.index 
            WHERE fi.feature_id IN ({feature_ids_str})
        """)
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
    if forage_cache.wait_ready(timeout=120):
        series = forage_cache.series("pollen", int(feature_id))
        if series is None:
            raise HTTPException(status_code=404, detail="Feature ID not found or no pollen data")
        return {"feature_id": feature_id, "pollen_timeseries": series}
    session = next(get_session())
    try:
        result = session.execute(text("""
            SELECT p.timeseries 
            FROM pollen p 
            JOIN feature_ids fi ON p.feature_index = fi.index 
            WHERE fi.feature_id = :feature_id
        """), {"feature_id": int(feature_id)})
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
        result = session.execute(text("""
            SELECT fi.feature_id, n.timeseries 
            FROM nectar n 
            JOIN feature_ids fi ON n.feature_index = fi.index 
            LIMIT 10
        """))
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
    if forage_cache.wait_ready(timeout=120):
        return {"nectar_data": [{"feature_id": f, "nectar_concentration": v, "date": date}
                                for f, v in forage_cache.day_values("nectar", date)], "date": date}
    session = next(get_session())
    try:
        result = session.execute(text("""
            SELECT fi.feature_id, n.timeseries 
            FROM nectar n 
            JOIN feature_ids fi ON n.feature_index = fi.index
        """))
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
    ids = _viewport_feature_ids(min_lng, min_lat, max_lng, max_lat)
    if ids is not None and forage_cache.wait_ready(timeout=120):
        return {"nectar_data": [{"feature_id": f, "nectar_concentration": v, "date": date}
                                for f, v in forage_cache.day_values("nectar", date, ids)], "date": date}
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
        nectar_query = text(f"""
            SELECT fi.feature_id, n.timeseries 
            FROM nectar n 
            JOIN feature_ids fi ON n.feature_index = fi.index 
            WHERE fi.feature_id IN ({feature_ids_str})
        """)
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
    if forage_cache.wait_ready(timeout=120):
        return {"pollen_data": [{"feature_id": f, "pollen_concentration": v, "date": date}
                                for f, v in forage_cache.day_values("pollen", date)], "date": date}
    session = next(get_session())
    try:
        result = session.execute(text("""
            SELECT fi.feature_id, p.timeseries 
            FROM pollen p 
            JOIN feature_ids fi ON p.feature_index = fi.index
        """))
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
    ids = _viewport_feature_ids(min_lng, min_lat, max_lng, max_lat)
    if ids is not None and forage_cache.wait_ready(timeout=120):
        return {"pollen_data": [{"feature_id": f, "pollen_concentration": v, "date": date}
                                for f, v in forage_cache.day_values("pollen", date, ids)], "date": date}
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
        
        from forage_cache import parse_day_index
        time_index = parse_day_index(date, 365)
        
        feature_ids_str = ','.join(map(str, viewport_feature_ids))
        pollen_query = text(f"""
            SELECT fi.feature_id, p.timeseries 
            FROM pollen p 
            JOIN feature_ids fi ON p.feature_index = fi.index 
            WHERE fi.feature_id IN ({feature_ids_str})
        """)
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
    if forage_cache.wait_ready(timeout=120):
        ids = [int(x) for x in feature_ids.split(',') if x.strip()] if feature_ids else None
        return {"averages": forage_cache.averages(ids, include_nectar, include_pollen)}
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
                nectar_query = text("""
                    SELECT n.timeseries 
                    FROM nectar n 
                    JOIN feature_ids fi ON n.feature_index = fi.index
                """)
            else:
                feature_ids_str = ','.join(map(str, feature_ids_list))
                nectar_query = text(f"""
                    SELECT n.timeseries 
                    FROM nectar n 
                    JOIN feature_ids fi ON n.feature_index = fi.index 
                    WHERE fi.feature_id IN ({feature_ids_str})
                """)
            
            nectar_result = session.execute(nectar_query)
            for row in nectar_result:
                timeseries = pickle.loads(row.timeseries)
                timeseries_clean = np.nan_to_num(timeseries, nan=0.0)
                nectar_timeseries.append(timeseries_clean)
        
        if include_pollen:
            # Single query to get all pollen timeseries
            if use_all_features:
                pollen_query = text("""
                    SELECT p.timeseries 
                    FROM pollen p 
                    JOIN feature_ids fi ON p.feature_index = fi.index
                """)
            else:
                feature_ids_str = ','.join(map(str, feature_ids_list))
                pollen_query = text(f"""
                    SELECT p.timeseries 
                    FROM pollen p 
                    JOIN feature_ids fi ON p.feature_index = fi.index 
                    WHERE fi.feature_id IN ({feature_ids_str})
                """)
            
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

@app.get("/api/applications")
def get_applications(feature_ids: str = None, run_id: int | None = None):
    """
    Get plant protection product application data.

    Reads from the applications table (populated at import time).
    Falls back to file-based resolution for legacy setups.
    """
    try:
        session = next(get_session())
        try:
            applications = _load_applications(session, run_id)
            if feature_ids:
                feature_id_list = _parse_feature_ids(feature_ids)
                applications = [
                    app for app in applications if app["lulc_feature_id"] in feature_id_list
                ]
            return {
                "applications": applications,
                "run_id": run_id,
            }
        finally:
            session.close()
    except HTTPException:
        raise
    except ValueError:
        return {"error": "Invalid feature_ids parameter"}
    except Exception as e:
        logger.error(f"Error reading applications data: {e}")
        return {"applications": [], "error": str(e)}

@app.get("/api/exposure/timeseries")
def get_exposure_timeseries(
    feature_ids: str = None,
    run_id: int | None = None,
    horizon_days: int | None = None,
):
    """
    Get exposure time series data for nectar, pollen, and contact values.
    
    For each application:
    1. Extend exposure for 9 days starting at application_day
    2. Sum overlapping exposures within the same feature
    3. Sum across all selected features for final daily values
    
    Args:
        feature_ids: Optional comma-separated list of feature IDs to filter by
        run_id: Optional run id to use run-specific applications file and time horizon
        horizon_days: Optional explicit horizon override (days)
    
    Returns:
        JSON with exposure time series for nectar, pollen, and contact
    """
    try:
        session = next(get_session())
        try:
            applications = _load_applications(session, run_id)
            if feature_ids:
                feature_id_list = _parse_feature_ids(feature_ids)
                applications = [
                    app for app in applications if app["lulc_feature_id"] in feature_id_list
                ]

            days = _resolve_exposure_horizon(session, run_id, applications, horizon_days)
            final_timeseries = _compute_exposure_timeseries(applications, days)
            return {
                "exposure_timeseries": final_timeseries,
                "horizon_days": days,
                "run_id": run_id,
            }
        finally:
            session.close()
    except HTTPException:
        raise
    except ValueError:
        return {"error": "Invalid feature_ids parameter"}
    except Exception as e:
        logger.error(f"Error calculating exposure timeseries: {e}")
        return {"exposure_timeseries": [], "error": str(e)}


def _parse_feature_ids(feature_ids: str) -> list[int]:
    return [int(fid.strip()) for fid in feature_ids.split(',') if fid.strip()]


def _load_applications(session, run_id: int | None) -> list[dict]:
    """Load applications from DB (preferred) or fall back to file resolution.

    Returns a list of dicts with keys: lulc_feature_id, application_day,
    conc_nectar, conc_pollen, contact.
    """
    if run_id is not None:
        # Try DB first
        rows = session.query(Application).filter_by(run_id=run_id).all()
        if rows:
            return [
                {
                    "lulc_feature_id": r.lulc_feature_id,
                    "application_day": r.application_day,
                    "conc_nectar": r.conc_nectar,
                    "conc_pollen": r.conc_pollen,
                    "contact": r.contact,
                }
                for r in rows
            ]

    # Fall back to file-based resolution (legacy / data/applications.txt)
    app_file = _resolve_applications_file(session, run_id)
    if app_file:
        return _read_applications_file(app_file)
    return []


def _read_applications_file(applications_file: str) -> list[dict]:
    applications = []
    with open(applications_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue

        parts = line.split(',')
        if len(parts) < 5:
            continue
        try:
            applications.append(
                {
                    "lulc_feature_id": int(parts[0]),
                    "application_day": int(parts[1]),
                    "conc_nectar": float(parts[2]),
                    "conc_pollen": float(parts[3]),
                    "contact": float(parts[4]),
                }
            )
        except (ValueError, IndexError):
            continue
    return applications


def _resolve_applications_file(session, run_id: int | None) -> str | None:
    """Resolve applications file path to the correct MC folder.

    Priority:
      1. run-scoped applications file from MC-specific folder (when run_id provided)
      2. default data/applications.txt

    source_path may be relative (portable DB) or absolute (legacy).
    Relative paths are resolved against CWD.
    """
    if run_id is not None:
        run = session.query(Run).filter_by(id=run_id).one_or_none()
        if run is None:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        source_path = run.source_path
        # Resolve relative paths against CWD for portability
        if source_path and not os.path.isabs(source_path):
            source_path = os.path.join(os.getcwd(), source_path)
        if source_path:
            # If MC folder is tracked in metadata, use it directly.
            if run.mc_folder_name:
                candidates = [
                    os.path.join(source_path, "mcs", run.mc_folder_name, "processing", "BeeHave", "applications.txt"),
                    os.path.join(source_path, "mcs", run.mc_folder_name, "processing", "BeeHaveEcotox", "applications.txt"),
                    os.path.join(source_path, "mcs", run.mc_folder_name, "BeeHaveEcotox", "applications.txt"),
                ]
                for path in candidates:
                    if os.path.exists(path):
                        return path

            # Fallback for legacy single-MC runs: search any MC folder.
            patterns = [
                os.path.join(source_path, "mcs", "*", "processing", "BeeHave", "applications.txt"),
                os.path.join(source_path, "mcs", "*", "processing", "BeeHaveEcotox", "applications.txt"),
                os.path.join(source_path, "mcs", "*", "BeeHaveEcotox", "applications.txt"),
            ]
            for pattern in patterns:
                matches = sorted(glob.glob(pattern))
                if matches:
                    return matches[0]

    default_file = "data/applications.txt"
    if os.path.exists(default_file):
        return default_file
    return None


def _resolve_exposure_horizon(
    session,
    run_id: int | None,
    applications: list[dict],
    explicit_horizon: int | None,
) -> int:
    if explicit_horizon is not None and explicit_horizon > 0:
        return explicit_horizon

    if run_id is not None:
        row = (
            session.query(BeePopulationReplicate)
            .filter_by(run_id=run_id)
            .order_by(BeePopulationReplicate.id)
            .first()
        )
        if row is not None:
            series = pickle.loads(row.timeseries)
            return int(len(series))

    if applications:
        max_app_day = max(app["application_day"] for app in applications)
        return max(365, max_app_day + 8)
    return 365


def _compute_exposure_timeseries(applications: list[dict], days: int) -> list[dict]:
    exposure_data = {}

    for app in applications:
        feature_id = app["lulc_feature_id"]
        start_day = app["application_day"]

        if feature_id not in exposure_data:
            exposure_data[feature_id] = {
                "nectar": [0.0] * days,
                "pollen": [0.0] * days,
                "contact": [0.0] * days,
            }

        for i in range(9):
            day_index = start_day + i - 1
            if 0 <= day_index < days:
                exposure_data[feature_id]["nectar"][day_index] += app["conc_nectar"]
                exposure_data[feature_id]["pollen"][day_index] += app["conc_pollen"]
                exposure_data[feature_id]["contact"][day_index] += app["contact"]

    final_timeseries = []
    for day in range(1, days + 1):
        day_index = day - 1
        final_timeseries.append(
            {
                "day": day,
                "nectar_exposure": sum(
                    feature_data["nectar"][day_index] for feature_data in exposure_data.values()
                ),
                "pollen_exposure": sum(
                    feature_data["pollen"][day_index] for feature_data in exposure_data.values()
                ),
                "contact_exposure": sum(
                    feature_data["contact"][day_index] for feature_data in exposure_data.values()
                ),
            }
        )
    return final_timeseries

# ---------------------------------------------------------------------------
# Multi-run endpoints
# ---------------------------------------------------------------------------


def _run_to_dict(run: Run) -> dict:
    return {
        "id": run.id,
        "sim_id": run.sim_id,
        "label": run.label,
        "scenario": run.scenario,
        "hive_group_id": run.hive_group_id,
        "batch_sim_id": getattr(run, "batch_sim_id", None),
        "outer_mc_id": getattr(run, "outer_mc_id", None),
        "mc_folder_name": getattr(run, "mc_folder_name", None),
        "treatment_on": bool(run.treatment_on),
        "n_replicates": run.n_replicates,
        "random_seed": run.random_seed,
        "hive_x": run.hive_x,
        "hive_y": run.hive_y,
        "hive_lon": run.hive_lon,
        "hive_lat": run.hive_lat,
        "source_path": run.source_path,
        "sim_start": getattr(run, "sim_start", None),
        "imported_at": run.imported_at.isoformat() if run.imported_at else None,
    }


@app.get("/api/runs")
def list_runs():
    """List all imported xPollinator runs, newest first."""
    session = next(get_session())
    try:
        runs = session.query(Run).order_by(Run.imported_at.desc()).all()
        return {"runs": [_run_to_dict(r) for r in runs]}
    finally:
        session.close()


@app.get("/api/runs/{run_id}")
def get_run(run_id: int):
    """Get a single run by numeric id."""
    session = next(get_session())
    try:
        run = session.query(Run).filter_by(id=run_id).one_or_none()
        if run is None:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        data = _run_to_dict(run)
        data["available_metrics"] = [
            m for (m,) in session.query(BeePopulationReplicate.metric_name)
            .filter_by(run_id=run_id)
            .distinct()
            .all()
        ]
        return data
    finally:
        session.close()


@app.get("/api/bee-population/replicates")
def get_bee_population_replicates(run_id: int, metric: str | None = None):
    """Per-replicate colony time series for a run.

    Response shape:
        {
          "run_id": X,
          "metrics": {
            "<metric_name>": {
              "replicate_count": N,
              "days": [1..n_steps],
              "mean":   [...],   # across replicates per day
              "p10":    [...],
              "p50":    [...],
              "p90":    [...],
              "min":    [...],
              "max":    [...],
              "replicates": [[day1, day2, ...], ...]   # n_replicates x n_days
            }, ...
          }
        }

    If `metric` is provided, only that metric is included.
    """
    session = next(get_session())
    try:
        if not session.query(Run).filter_by(id=run_id).first():
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        query = session.query(BeePopulationReplicate).filter_by(run_id=run_id)
        if metric:
            query = query.filter_by(metric_name=metric)
        rows = query.order_by(
            BeePopulationReplicate.metric_name, BeePopulationReplicate.replicate_idx
        ).all()
        if not rows:
            return {"run_id": run_id, "metrics": {}}

        metrics: dict[str, dict] = {}
        by_metric: dict[str, list[tuple[int, np.ndarray]]] = {}
        for row in rows:
            arr = pickle.loads(row.timeseries)
            by_metric.setdefault(row.metric_name, []).append((row.replicate_idx, arr))

        for metric_name, replicates in by_metric.items():
            replicates.sort(key=lambda t: t[0])
            matrix = np.vstack([arr for _, arr in replicates])  # (n_rep, n_days)
            n_days = matrix.shape[1]
            metrics[metric_name] = {
                "replicate_count": matrix.shape[0],
                "days": list(range(1, n_days + 1)),
                "mean": matrix.mean(axis=0).tolist(),
                "p10": np.percentile(matrix, 10, axis=0).tolist(),
                "p50": np.percentile(matrix, 50, axis=0).tolist(),
                "p90": np.percentile(matrix, 90, axis=0).tolist(),
                "min": matrix.min(axis=0).tolist(),
                "max": matrix.max(axis=0).tolist(),
                "replicates": matrix.tolist(),
            }
        return {"run_id": run_id, "metrics": metrics}
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Compare endpoints
# ---------------------------------------------------------------------------


@app.get("/api/compare/relative")
def api_compare_relative(baseline_id: int, scenario_id: int, metric: str):
    """Relative change of metric (scenario - baseline) / baseline per day.

    Pairs replicates by index across the two runs (shorter run wins).
    Returns mean across pairs plus p10/p50/p90 of the relative change distribution.
    """
    session = next(get_session())
    try:
        rel = compute_relative(session, baseline_id, scenario_id, metric)
        if rel is None:
            raise HTTPException(
                status_code=404,
                detail=f"No data for runs {baseline_id}/{scenario_id} metric '{metric}'",
            )
        n_days = rel.shape[1]
        return {
            "baseline_id": baseline_id,
            "scenario_id": scenario_id,
            "metric": metric,
            "n_pairs": int(rel.shape[0]),
            "days": list(range(1, n_days + 1)),
            "mean": np.nanmean(rel, axis=0).tolist(),
            **compute_percentiles_relative(rel),
        }
    finally:
        session.close()


@app.get("/api/compare/exceedance")
def api_compare_exceedance(
    baseline_id: int,
    scenario_id: int,
    metric: str,
    threshold: float = 0.10,
    mode: str = "decline",
):
    """Per-day fraction of replicate pairs exceeding threshold in selected mode.

    Modes:
      - decline: rel <= -threshold
      - absolute: |rel| > threshold
    """
    if mode not in {"decline", "absolute"}:
        raise HTTPException(status_code=400, detail="mode must be 'decline' or 'absolute'")
    session = next(get_session())
    try:
        rel = compute_relative(session, baseline_id, scenario_id, metric)
        if rel is None:
            raise HTTPException(
                status_code=404,
                detail=f"No data for runs {baseline_id}/{scenario_id} metric '{metric}'",
            )
        exc = compute_exceedance(rel, threshold, mode)
        return {
            "baseline_id": baseline_id,
            "scenario_id": scenario_id,
            "metric": metric,
            "threshold": threshold,
            "mode": mode,
            "n_pairs": int(rel.shape[0]),
            "days": list(range(1, exc.shape[0] + 1)),
            "exceedance_fraction": exc.tolist(),
        }
    finally:
        session.close()


@app.get("/api/compare/percentiles")
def api_compare_percentiles(
    baseline_ids: str,
    scenario_ids: str,
    metric: str,
    threshold: float = 0.10,
    mode: str = "decline",
    spatial_scope: str = "pair",
):
    """Spatial (across hives, per day) and temporal (across days, per hive)
    percentiles of the per-(hive, day) exceedance fraction.

    `baseline_ids` and `scenario_ids` are comma-separated lists of integer
    run IDs, parallel by index — index i defines one hive's pair.
    """
    try:
        bs = [int(x) for x in baseline_ids.split(",") if x.strip()]
        ss = [int(x) for x in scenario_ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(
            status_code=400, detail="baseline_ids/scenario_ids must be comma-separated integers"
        )
    if len(bs) != len(ss):
        raise HTTPException(
            status_code=400, detail="baseline_ids and scenario_ids must have equal length"
        )
    if mode not in {"decline", "absolute"}:
        raise HTTPException(status_code=400, detail="mode must be 'decline' or 'absolute'")
    if spatial_scope not in {"pair", "hive_mean"}:
        raise HTTPException(status_code=400, detail="spatial_scope must be 'pair' or 'hive_mean'")
    session = next(get_session())
    try:
        result = compute_percentiles_pairs(
            session,
            bs,
            ss,
            metric,
            threshold,
            mode,
            spatial_scope=spatial_scope,
        )
        result.update({
            "metric": metric,
            "threshold": threshold,
            "mode": mode,
            "spatial_scope": spatial_scope,
        })
        return result
    finally:
        session.close()


@app.get("/api/compare/reduction-matrix")
def api_compare_reduction_matrix(
    baseline_ids: str,
    scenario_ids: str,
    metric: str,
    spatial_scope: str = "pair",
):
    """Percent-reduction percentile matrix.

    Each cell (pS, pT) = actual percent-reduction of treated vs untreated
    at the pS-th spatial percentile and pT-th temporal percentile.
    No threshold parameter — the cell value IS the reduction magnitude.
    """
    try:
        bs = [int(x) for x in baseline_ids.split(",") if x.strip()]
        ss = [int(x) for x in scenario_ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(
            status_code=400, detail="baseline_ids/scenario_ids must be comma-separated integers"
        )
    if len(bs) != len(ss):
        raise HTTPException(
            status_code=400, detail="baseline_ids and scenario_ids must have equal length"
        )
    if spatial_scope not in {"pair", "hive_mean"}:
        raise HTTPException(status_code=400, detail="spatial_scope must be 'pair' or 'hive_mean'")
    session = next(get_session())
    try:
        return compute_reduction_matrix(session, bs, ss, metric, spatial_scope=spatial_scope)
    finally:
        session.close()


@app.get("/api/compare/ed-matrix")
def api_compare_ed_matrix(
    baseline_ids: str,
    scenario_ids: str,
    metric: str,
    threshold: float = 0.10,
):
    """Effect-Days (ED) percentile matrix.

    For each replicate at each hive location, counts the number of days where
    the scenario metric falls below baseline * (1 - threshold).  Returns a 10x10
    matrix: rows = temporal percentiles (p10..p100 across replicates),
    cols = spatial percentiles (p10..p100 across hive locations).

    `baseline_ids` and `scenario_ids` are comma-separated integer run IDs,
    parallel by index — index i defines one hive location's paired runs.
    """
    try:
        bs = [int(x) for x in baseline_ids.split(",") if x.strip()]
        ss = [int(x) for x in scenario_ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(
            status_code=400, detail="baseline_ids/scenario_ids must be comma-separated integers"
        )
    if len(bs) != len(ss):
        raise HTTPException(
            status_code=400, detail="baseline_ids and scenario_ids must have equal length"
        )
    session = next(get_session())
    try:
        return compute_ed_matrix(session, bs, ss, metric, threshold)
    finally:
        session.close()


@app.get("/api/compare/survival")
def api_compare_survival(
    baseline_ids: str,
    scenario_ids: str,
):
    """Overwintering survival probability per hive location.

    For each paired (baseline, scenario) run, computes the fraction of
    replicates where adult bees (TotalIHbees + TotalForagers) on the last
    simulation day >= 4000 (CRITICAL_COLONY_SIZE_WINTER).

    Returns survival probabilities and absolute effect per hive.
    `baseline_ids` and `scenario_ids` are comma-separated integer run IDs.
    """
    try:
        bs = [int(x) for x in baseline_ids.split(",") if x.strip()]
        ss = [int(x) for x in scenario_ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(
            status_code=400, detail="baseline_ids/scenario_ids must be comma-separated integers"
        )
    if len(bs) != len(ss):
        raise HTTPException(
            status_code=400, detail="baseline_ids and scenario_ids must have equal length"
        )
    session = next(get_session())
    try:
        return compute_survival_probabilities(session, bs, ss)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Simulation Management API
# ---------------------------------------------------------------------------
from simulation import start_simulation, get_job, list_jobs, cancel_job
from scenarios import list_scenarios, get_scenario_bounds
from pydantic import BaseModel
from typing import Optional


class SimulationRequest(BaseModel):
    SimID: str
    Project: str
    SimulationStart: str = "2021-01-01"
    SimulationEnd: str = "2021-12-31"
    NumberBeeHaveTimesteps: int = 365
    BeeHaveMapCenterPointX: float
    BeeHaveMapCenterPointY: float
    NumberBeeHaveReplicates: int = 1
    BeeHaveRandomSeed: int = 1
    BeeHaveWeather: str = "Rothamsted (2009)"
    BeeHaveWeatherFile: Optional[str] = None
    MinNumberApplications: int = 0
    MaxNumberApplications: int = 0
    RunLabel: Optional[str] = None
    HiveGroupId: Optional[str] = None
    NumberMC: Optional[int] = 1


@app.get("/api/scenarios")
def api_list_scenarios():
    """List available xPollinator scenarios."""
    return list_scenarios()


@app.get("/api/scenarios/{folder_name}/bounds")
def api_scenario_bounds(folder_name: str):
    """Get geographic bounds for a scenario (for map centering and hive placement)."""
    bounds = get_scenario_bounds(folder_name)
    if bounds is None:
        raise HTTPException(status_code=404, detail=f"Scenario not found or no shapefile: {folder_name}")
    return bounds


@app.post("/api/simulate")
def api_start_simulation(request: SimulationRequest):
    """Start a new xPollinator simulation."""
    params = request.model_dump(exclude_none=True)
    # Use SimID as RunLabel if not provided
    if not params.get("RunLabel"):
        params["RunLabel"] = params["SimID"]
    if not params.get("HiveGroupId"):
        params["HiveGroupId"] = params["SimID"]

    job_id, error = start_simulation(params)
    if error:
        raise HTTPException(status_code=400, detail=error)
    return {"job_id": job_id, "sim_id": params["SimID"]}


@app.get("/api/simulate/jobs")
def api_list_jobs():
    """List all simulation jobs."""
    return list_jobs()


@app.get("/api/simulate/jobs/{job_id}")
def api_get_job(job_id: str):
    """Get status of a specific simulation job."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_dict()


@app.delete("/api/simulate/jobs/{job_id}")
def api_cancel_job(job_id: str):
    """Cancel a running or queued simulation."""
    error = cancel_job(job_id)
    if error:
        raise HTTPException(status_code=400, detail=error)
    return {"status": "cancelled"}


# ---------------------------------------------------------------------------
# Serve built frontend (BeeView dist/) if the folder exists.
# Must be mounted AFTER all /api routes so API takes priority.
# ---------------------------------------------------------------------------
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "frontend")
if os.path.isdir(FRONTEND_DIR) and os.path.isfile(os.path.join(FRONTEND_DIR, "index.html")):
    # Serve static assets (js, css, images)
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIR, "assets")), name="frontend-assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        """SPA catch-all: serve file if it exists, otherwise index.html."""
        file_path = os.path.join(FRONTEND_DIR, full_path)
        if full_path and os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=32000)
