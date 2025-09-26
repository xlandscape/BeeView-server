import json
import logging
from models import VegetationClassMapping

logger = logging.getLogger(__name__)

def load_vegetation_classes_to_db(json_path: str, db_session):
    """Load vegetation class mapping from JSON file to database"""
    try:
        with open(json_path, 'r') as f:
            vegetation_data = json.load(f)

        logger.info(f"Loading {len(vegetation_data)} vegetation class mappings")

        # Clear existing data
        db_session.query(VegetationClassMapping).delete()

        # Insert new data
        for vegetation_name, vegetation_class in vegetation_data.items():
            mapping_obj = VegetationClassMapping(
                vegetation_name=vegetation_name,
                vegetation_class=vegetation_class
            )
            db_session.add(mapping_obj)

        db_session.commit()
        logger.info(f"Successfully loaded {len(vegetation_data)} vegetation class mappings")

    except Exception as e:
        logger.error(f"Error loading vegetation classes: {e}")
        db_session.rollback()
        raise