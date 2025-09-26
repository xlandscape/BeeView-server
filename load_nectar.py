import h5py
import numpy as np
import pickle
import logging
from sqlalchemy import text
from models import Nectar

logger = logging.getLogger(__name__)

def load_nectar_to_db(hdf_path: str, db_session):
    with h5py.File(hdf_path, "r") as f:
        nectar = f["BeeForage/Nectar"][:]

        # Clear existing nectar data
        db_session.execute(text("DELETE FROM nectar"))

        # Get all feature_ids with their indices
        result = db_session.execute(text("SELECT index, feature_id FROM feature_ids ORDER BY index"))
        feature_indices = list(result.fetchall())
        logger.info(f"Found {len(feature_indices)} feature indices.")

        nectar_rows = nectar.shape[0]
        loaded_count = 0

        for feature_index, feature_id in feature_indices:
            # feature_index corresponds directly to the HDF array index
            if feature_index >= nectar_rows:
                continue

            timeseries = nectar[feature_index, :]
            nectar_obj = Nectar(feature_index=feature_index, timeseries=pickle.dumps(timeseries))
            db_session.add(nectar_obj)
            loaded_count += 1

        db_session.commit()
        logger.info(f"Loaded nectar data for {loaded_count} features")
