import geopandas as gpd
from models import Feature
from shapely.geometry import MultiPolygon
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def load_shapefile_to_db(shapefile_path: str, db_session):
    gdf = gpd.read_file(shapefile_path)
    logger.info(f"Shapefile CRS: {gdf.crs}")
    logger.info(f"First geometry (raw): {gdf.iloc[0].geometry}")
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        logger.info("Reprojecting to EPSG:4326")
        gdf = gdf.to_crs(epsg=4326)
    logger.info(f"First geometry WKT (to be saved): {gdf.iloc[0].geometry.wkt}")
    features = []
    for _, row in gdf.iterrows():
        geom = row['geometry']
        if geom is None or geom.is_empty:
            continue
        # Ensure MultiPolygon
        if geom.geom_type == 'Polygon':
            geom = MultiPolygon([geom])
        feature = Feature(
            name=str(row.get('name', '')),  # Adjust property names as needed
            lulc_label=str(row.get('L1_label', '')),  # Adjust property names as needed
            geometry=geom.wkt
        )
        db_session.add(feature)
    db_session.commit()
