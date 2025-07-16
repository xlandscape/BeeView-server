import h5py
import numpy as np
import pickle
from sqlalchemy import text
from models import Nectar

def load_nectar_to_db(hdf_path: str, db_session):
    with h5py.File(hdf_path, "r") as f:
        nectar = f["BeeForage/Nectar"][:]
        result = db_session.execute(text("SELECT id FROM features ORDER BY id"))
        feature_ids = [row[0] for row in result]
        nectar_rows = nectar.shape[0]
        for idx, feature_id in enumerate(feature_ids):
            if idx >= nectar_rows:
                break
            timeseries = nectar[idx, :]
            nectar_obj = Nectar(feature_id=feature_id, timeseries=pickle.dumps(timeseries))
            db_session.add(nectar_obj)
        db_session.commit()
