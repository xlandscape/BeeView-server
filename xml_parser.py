"""
XML parser utilities for BeeForage configuration files.
"""
import xml.etree.ElementTree as ET
import os
from pathlib import Path
from typing import Optional, Tuple
import geopandas as gpd
from shapely.geometry import Point


DEFAULT_TEMPLATE_PATH = "../xPollinator/template.xrun"


def resolve_template_xrun_path(template_path: str = DEFAULT_TEMPLATE_PATH) -> Path:
    """Resolve the BeeHave template path against the current repo layout."""
    candidate = Path(template_path)
    if candidate.is_absolute() and candidate.exists():
        return candidate

    server_dir = Path(__file__).resolve().parent
    env_path = os.getenv("BEEHIVE_TEMPLATE_PATH")
    candidate_paths = []

    if env_path:
        candidate_paths.append(Path(env_path))

    candidate_paths.extend([
        server_dir / template_path,
        server_dir / "../xPollinator/template.xrun",
        server_dir / "../template.xrun",
        Path.cwd() / template_path,
    ])

    for path in candidate_paths:
        resolved = path.resolve()
        if resolved.exists():
            return resolved

    return (server_dir / template_path).resolve()


def parse_template_xrun(file_path: str) -> Optional[Tuple[float, float]]:
    """
    Parse template.xrun file to extract BeeHave map center point coordinates.
    
    Args:
        file_path: Path to the template.xrun file
        
    Returns:
        Tuple of (x, y) coordinates in meters, or None if parsing fails
    """
    try:
        # Parse the XML file
        tree = ET.parse(file_path)
        root = tree.getroot()
        
        # Define the namespace
        namespace = {'ns': 'urn:xBeeForage'}
        
        # Extract coordinates
        x_element = root.find('.//ns:BeeHaveMapCenterPointX', namespace)
        y_element = root.find('.//ns:BeeHaveMapCenterPointY', namespace)
        
        if x_element is not None and y_element is not None:
            x_coord = float(x_element.text)
            y_coord = float(y_element.text)
            return (x_coord, y_coord)
        else:
            # Try without namespace (fallback)
            x_element = root.find('.//BeeHaveMapCenterPointX')
            y_element = root.find('.//BeeHaveMapCenterPointY')
            
            if x_element is not None and y_element is not None:
                x_coord = float(x_element.text)
                y_coord = float(y_element.text)
                return (x_coord, y_coord)
            
        return None
        
    except (ET.ParseError, ValueError, FileNotFoundError) as e:
        print(f"Error parsing template.xrun: {e}")
        return None


def transform_coordinates_to_wgs84(x: float, y: float, source_crs: str = None) -> Optional[Tuple[float, float]]:
    """
    Transform coordinates from projected CRS to WGS84 (EPSG:4326).
    
    Args:
        x: X coordinate in projected system
        y: Y coordinate in projected system
        source_crs: Source CRS (if None, will try to detect from shapefile)
        
    Returns:
        Tuple of (longitude, latitude) in WGS84, or None if transformation fails
    """
    try:
        # If no source CRS provided, try to read from shapefile
        if source_crs is None:
            shapefile_path = Path(__file__).parent / "data" / "lulc.shp"
            if shapefile_path.exists():
                gdf = gpd.read_file(str(shapefile_path))
                source_crs = gdf.crs
                print(f"Detected CRS from shapefile: {source_crs}")
            else:
                # Default to Web Mercator (EPSG:3857) which matches the BeeView-server data pipeline
                source_crs = "EPSG:3857"
                print(f"Shapefile not found, assuming CRS: {source_crs}")
        
        # Create a point in the source CRS
        point = Point(x, y)
        gdf = gpd.GeoDataFrame([1], geometry=[point], crs=source_crs)
        
        # Transform to WGS84
        gdf_wgs84 = gdf.to_crs("EPSG:4326")
        transformed_point = gdf_wgs84.geometry.iloc[0]
        
        return (transformed_point.x, transformed_point.y)
        
    except Exception as e:
        print(f"Error transforming coordinates: {e}")
        return None


from functools import lru_cache


@lru_cache(maxsize=8)
def get_beehive_location(template_path: str = DEFAULT_TEMPLATE_PATH) -> Optional[dict]:
    """
    Get beehive location from template.xrun file and transform to WGS84.
    
    Args:
        template_path: Path to template.xrun file relative to server directory
        
    Returns:
        Dictionary with x, y coordinates in WGS84 and metadata, or None if not found
    """
    full_path = resolve_template_xrun_path(template_path)
    
    coordinates = parse_template_xrun(str(full_path))
    
    if coordinates:
        x_proj, y_proj = coordinates
        
        # Transform to WGS84 for use in web map
        wgs84_coords = transform_coordinates_to_wgs84(x_proj, y_proj)
        
        if wgs84_coords:
            lon, lat = wgs84_coords
            return {
                "x": lon,  # Longitude for web map
                "y": lat,  # Latitude for web map
                "x_projected": x_proj,  # Original projected coordinates
                "y_projected": y_proj,
                "description": "BeeHave Map Center Point",
                "source": "template.xrun",
                "crs": "EPSG:4326"  # Transformed coordinates
            }
        else:
            # Fallback: return original coordinates with warning
            print("Warning: Could not transform coordinates, returning original values")
            return {
                "x": x_proj,
                "y": y_proj,
                "description": "BeeHave Map Center Point (untransformed)",
                "source": "template.xrun",
                "crs": "unknown"
            }
    
    return None


def create_beehive_buffer(radius_km: float = 10.0, template_path: str = DEFAULT_TEMPLATE_PATH) -> Optional[gpd.GeoDataFrame]:
    """
    Create a buffer around the beehive location for filtering geometries.
    
    Args:
        radius_km: Radius in kilometers around the beehive location
        template_path: Path to template.xrun file relative to server directory
        
    Returns:
        GeoDataFrame with buffer polygon in the original CRS, or None if beehive location not found
    """
    try:
        # Get beehive location in projected coordinates
        full_path = resolve_template_xrun_path(template_path)
        coordinates = parse_template_xrun(str(full_path))
        
        if not coordinates:
            return None
            
        x_proj, y_proj = coordinates
        
        # Determine the source CRS
        shapefile_path = Path(__file__).parent / "data" / "Tarn_LULC_v04.shp"
        source_crs = "EPSG:32631"  # Default to UTM Zone 31N for France
        
        if shapefile_path.exists():
            gdf = gpd.read_file(str(shapefile_path))
            source_crs = gdf.crs
        
        # Create point in projected CRS
        beehive_point = Point(x_proj, y_proj)
        
        # Create GeoDataFrame with the point
        point_gdf = gpd.GeoDataFrame([1], geometry=[beehive_point], crs=source_crs)
        
        # Create buffer (radius in meters = radius_km * 1000)
        buffer_gdf = point_gdf.copy()
        buffer_gdf.geometry = point_gdf.geometry.buffer(radius_km * 1000)
        
        print(f"Created buffer with {radius_km}km radius around beehive location")
        return buffer_gdf
        
    except Exception as e:
        print(f"Error creating beehive buffer: {e}")
        return None


@lru_cache(maxsize=8)
def get_beehive_buffer_bounds(radius_km: float = 10.0, template_path: str = DEFAULT_TEMPLATE_PATH) -> Optional[dict]:
    """
    Get the bounding box of the beehive buffer area.
    
    Args:
        radius_km: Radius in kilometers around the beehive location
        template_path: Path to template.xrun file relative to server directory
        
    Returns:
        Dictionary with bounding box coordinates, or None if beehive location not found
    """
    buffer_gdf = create_beehive_buffer(radius_km, template_path)
    
    if buffer_gdf is not None:
        # Get bounds in original CRS
        bounds = buffer_gdf.total_bounds  # [minx, miny, maxx, maxy]
        
        # Also get bounds in WGS84 for web map use
        buffer_wgs84 = buffer_gdf.to_crs("EPSG:4326")
        bounds_wgs84 = buffer_wgs84.total_bounds
        
        return {
            "bounds_projected": {
                "minx": float(bounds[0]),
                "miny": float(bounds[1]), 
                "maxx": float(bounds[2]),
                "maxy": float(bounds[3])
            },
            "bounds_wgs84": {
                "minx": float(bounds_wgs84[0]),  # min longitude
                "miny": float(bounds_wgs84[1]),  # min latitude
                "maxx": float(bounds_wgs84[2]),  # max longitude
                "maxy": float(bounds_wgs84[3])   # max latitude
            },
            "radius_km": radius_km
        }
    
    return None