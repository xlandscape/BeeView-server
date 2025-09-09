import h5py
import numpy as np
import pickle
import logging
from sqlalchemy import text
from models import Pollen

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def load_pollen_to_db(hdf_path: str, db_session):
    with h5py.File(hdf_path, "r") as f:
        pollen = f["BeeForage/Pollen"][:]
        result = db_session.execute(text("SELECT id FROM features ORDER BY id"))
        feature_ids = [row[0] for row in result]
        logger.info(f"Loaded {len(feature_ids)} feature IDs from the hdf file.")
        pollen_rows = pollen.shape[0]
        for idx, feature_id in enumerate(feature_ids):
            if idx >= pollen_rows:
                break
            timeseries = pollen[idx, :]
            pollen_obj = Pollen(feature_id=feature_id, timeseries=pickle.dumps(timeseries))
            db_session.add(pollen_obj)
        db_session.commit()
