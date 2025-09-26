import h5py
import logging
from models import FeatureIds

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def load_feature_ids_to_db(hdf_path: str, db_session):
    """Load feature IDs from HDF5 LandscapeScenario/FeatureIds to database"""
    try:
        with h5py.File(hdf_path, "r") as f:
            if "LandscapeScenario/FeatureIds" not in f:
                logger.error("LandscapeScenario/FeatureIds not found in HDF file")
                return

            feature_ids_data = f["LandscapeScenario/FeatureIds"][:]
            logger.info(f"Loading {len(feature_ids_data)} feature IDs from HDF file")

            # Clear existing data
            db_session.query(FeatureIds).delete()

            # Insert new data
            for index, feature_id in enumerate(feature_ids_data):
                feature_id_obj = FeatureIds(index=index, feature_id=int(feature_id))
                db_session.add(feature_id_obj)

            db_session.commit()
            logger.info(f"Successfully loaded {len(feature_ids_data)} feature IDs")

    except Exception as e:
        logger.error(f"Error loading feature IDs: {e}")
        db_session.rollback()
        raise