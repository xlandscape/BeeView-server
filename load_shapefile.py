import geopandas as gpd
from models import Feature, FeatureIds
from shapely.geometry import MultiPolygon, Polygon
import logging
import numpy as np
from xml_parser import create_beehive_buffer
from sqlalchemy import text

logger = logging.getLogger(__name__)

def strip_z_from_geom(geom):
    # Remove Z from all coordinates in Polygon or MultiPolygon
    if geom is None or geom.is_empty:
        return geom
    if geom.geom_type == 'Polygon':
        exterior = [(x, y) for x, y, *_ in geom.exterior.coords]
        interiors = [
            [(x, y) for x, y, *_ in ring.coords]
            for ring in geom.interiors
        ]
        return Polygon(exterior, interiors)
    elif geom.geom_type == 'MultiPolygon':
        polygons = [strip_z_from_geom(poly) for poly in geom.geoms]
        return MultiPolygon(polygons)
    return geom

def load_shapefile_to_db(shapefile_path: str, db_session, subset_size: int = 1000, beehive_radius_km: float = None):
    gdf = gpd.read_file(shapefile_path)
    logger.info(f"Shapefile CRS: {gdf.crs}")
    logger.info(f"Total features in shapefile: {len(gdf)}")
    logger.debug(f"First geometry (raw): {gdf.iloc[0].geometry}")
    
    original_crs = gdf.crs
    
    # Apply beehive radius filter if specified
    if beehive_radius_km is not None and beehive_radius_km > 0:
        logger.info(f"Applying beehive radius filter: {beehive_radius_km}km")
        
        # Get buffer around beehive location in the original CRS
        buffer_gdf = create_beehive_buffer(beehive_radius_km)
        
        if buffer_gdf is not None:
            # Ensure both GeoDataFrames are in the same CRS
            buffer_gdf = buffer_gdf.to_crs(original_crs)
            
            # Filter geometries that intersect with the buffer
            intersects = gdf.geometry.intersects(buffer_gdf.geometry.iloc[0])
            gdf_filtered = gdf[intersects].copy()
            
            logger.info(f"Features after radius filter: {len(gdf_filtered)} (reduced from {len(gdf)})")
            gdf = gdf_filtered
        else:
            logger.warning("Could not create beehive buffer, loading all features")
    
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        logger.info("Reprojecting to EPSG:4326")
        gdf = gdf.to_crs(epsg=4326)
    logger.debug(f"First geometry WKT (to be saved): {gdf.iloc[0].geometry.wkt}")
    
    # Select a random subset after radius filtering
    if len(gdf) > subset_size:
        logger.info(f"Number of geometries is {len(gdf)}. Selecting random subset of size {subset_size}")
        gdf = gdf.sample(n=subset_size, random_state=None)

    # Clear existing features
    db_session.query(Feature).delete()

    # Get available feature IDs from the feature_ids table
    result = db_session.execute(text("SELECT feature_id FROM feature_ids ORDER BY feature_id"))
    available_feature_ids = [row[0] for row in result.fetchall()]
    logger.info(f"Available feature IDs: {len(available_feature_ids)}")

    feature_id_index = 0
    for _, row in gdf.iterrows():
        geom = row['geometry']
        if geom is None or geom.is_empty:
            continue

        # Skip if we've run out of feature IDs
        if feature_id_index >= len(available_feature_ids):
            logger.warning(f"Ran out of feature IDs. Only loaded {feature_id_index} features out of {len(gdf)}")
            break

        # Ensure MultiPolygon
        if geom.geom_type == 'Polygon':
            geom = MultiPolygon([geom])
        # Strip Z from all polygons
        geom_2d = strip_z_from_geom(geom)

        feature = Feature(
            feature_id=available_feature_ids[feature_id_index],
            name=str(row.get('name', '')),  # Adjust property names as needed
            l1_code=int(row.get('L1_code')) if row.get('L1_code') is not None else None,
            l1_label=str(row.get('L1_label', '')),
            l2_code=int(row.get('L2_code')) if row.get('L2_code') is not None else None,
            l2_label=str(row.get('L2_label', '')) if row.get('L2_label') else None,
            l3_code=int(row.get('L3_code')) if row.get('L3_code') is not None else None,
            l3_label=str(row.get('L3_label', '')) if row.get('L3_label') else None,
            geometry=geom_2d.wkt
        )
        db_session.add(feature)
        feature_id_index += 1

    db_session.commit()
    logger.info(f"Loaded {feature_id_index} features with mapped feature IDs")
