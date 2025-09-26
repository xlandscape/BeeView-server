import h5py
import logging
from models import Vegetation

logger = logging.getLogger(__name__)

def load_vegetation_to_db(hdf_path: str, db_session):
    """Load vegetation data from HDF5 Vegetation/Vegetation to database"""
    try:
        with h5py.File(hdf_path, "r") as f:
            if "Vegetation/Vegetation" not in f:
                logger.error("Vegetation/Vegetation not found in HDF file")
                return

            vegetation_data = f["Vegetation/Vegetation"][:]
            logger.info(f"Loading {len(vegetation_data)} vegetation mappings from HDF file")

            # Clear existing data
            db_session.query(Vegetation).delete()

            # Insert new data
            for feature_index, vegetation_class in enumerate(vegetation_data):
                vegetation_obj = Vegetation(
                    feature_index=feature_index,
                    vegetation_class=int(vegetation_class)
                )
                db_session.add(vegetation_obj)

            db_session.commit()
            logger.info(f"Successfully loaded {len(vegetation_data)} vegetation mappings")

    except Exception as e:
        logger.error(f"Error loading vegetation data: {e}")
        db_session.rollback()
        raise