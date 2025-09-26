import h5py
import numpy as np
import pickle
import logging
from sqlalchemy import text
from models import Pollen

logger = logging.getLogger(__name__)

def load_pollen_to_db(hdf_path: str, db_session):
    with h5py.File(hdf_path, "r") as f:
        pollen = f["BeeForage/Pollen"][:]

        # Clear existing pollen data
        db_session.execute(text("DELETE FROM pollen"))

        # Get all feature_ids with their indices
        result = db_session.execute(text("SELECT index, feature_id FROM feature_ids ORDER BY index"))
        feature_indices = list(result.fetchall())
        logger.info(f"Found {len(feature_indices)} feature indices.")

        pollen_rows = pollen.shape[0]
        loaded_count = 0

        for feature_index, feature_id in feature_indices:
            # feature_index corresponds directly to the HDF array index
            if feature_index >= pollen_rows:
                continue

            timeseries = pollen[feature_index, :]
            pollen_obj = Pollen(feature_index=feature_index, timeseries=pickle.dumps(timeseries))
            db_session.add(pollen_obj)
            loaded_count += 1

        db_session.commit()
        logger.info(f"Loaded pollen data for {loaded_count} features")
