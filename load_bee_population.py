#!/usr/bin/env python3
"""
Load bee population data from output.csv into the database
"""

import pandas as pd
import pickle
import numpy as np
import logging
from sqlalchemy.orm import Session
from models import BeePopulation

logger = logging.getLogger(__name__)


RAW_METRICS = [
    "TotalIHbees",
    "TotalForagers",
    "TotalDroneEggs",
    "TotalEggs",
    "TotalDroneLarvae",
    "TotalLarvae",
    "TotalDronePupae",
    "TotalPupae",
]

DERIVED_METRICS = {
    "TotalIHbees + TotalForagers + TotalDroneEggs + TotalEggs + TotalDroneLarvae + TotalLarvae + TotalDronePupae + TotalPupae": [
        "TotalIHbees",
        "TotalForagers",
        "TotalDroneEggs",
        "TotalEggs",
        "TotalDroneLarvae",
        "TotalLarvae",
        "TotalDronePupae",
        "TotalPupae",
    ],
    "TotalIHbees + TotalForagers": ["TotalIHbees", "TotalForagers"],
    "TotalDroneEggs + TotalEggs": ["TotalDroneEggs", "TotalEggs"],
    "TotalDroneLarvae + TotalLarvae": ["TotalDroneLarvae", "TotalLarvae"],
    "TotalDronePupae + TotalPupae": ["TotalDronePupae", "TotalPupae"],
}

OPTIONAL_DIRECT_METRICS = ["HoneyEnergyStore", "PollenStore_g"]


def _metric_array(df: pd.DataFrame, metric_name: str) -> np.ndarray | None:
    """Return metric array from a direct column or a derived formula."""
    if metric_name in df.columns:
        return df[metric_name].to_numpy(dtype=np.float64)

    formula = DERIVED_METRICS.get(metric_name)
    if not formula:
        return None

    missing = [name for name in formula if name not in df.columns]
    if missing:
        return None

    return sum(df[name].to_numpy(dtype=np.float64) for name in formula)

def load_bee_population_to_db(csv_path: str, session: Session):
    """Load bee population data from CSV to database."""
    logger.info(f"Loading bee population data from {csv_path}")
    
    # Clear existing bee population data
    session.query(BeePopulation).delete()
    
    # Read CSV file, skip first 6 rows, use row 7 as headers
    df = pd.read_csv(csv_path, skiprows=6)
    
    metrics = list(dict.fromkeys([
        *DERIVED_METRICS.keys(),
        *OPTIONAL_DIRECT_METRICS,
        *RAW_METRICS,
    ]))
    
    # Store each metric as a separate record
    for metric in metrics:
        timeseries_array = _metric_array(df, metric)
        if timeseries_array is None:
            logger.info(f"Skipping unavailable metric: {metric}")
            continue

        timeseries_array = np.nan_to_num(timeseries_array, nan=0.0, posinf=0.0, neginf=0.0)
        timeseries_blob = pickle.dumps(timeseries_array)

        bee_pop_record = BeePopulation(
            metric_name=metric,
            timeseries=timeseries_blob
        )

        session.add(bee_pop_record)
        logger.info(f"Added {metric}: {len(timeseries_array)} time points")
    
    session.commit()
    logger.info("Bee population data loading completed!")

if __name__ == "__main__":
    # Test loading
    session = next(get_session())
    try:
        load_bee_population_to_db("data/output.csv", session)
    finally:
        session.close()
