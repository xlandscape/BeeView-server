#!/usr/bin/env python3
"""
Load bee population data from output.csv into the database
"""

import pandas as pd
import pickle
import numpy as np
from sqlalchemy.orm import Session
from models import BeePopulation

def load_bee_population_to_db(csv_path: str, session: Session):
    """Load bee population data from CSV to database."""
    print(f"Loading bee population data from {csv_path}")
    
    # Clear existing bee population data
    session.query(BeePopulation).delete()
    
    # Read CSV file, skip first 6 rows, use row 7 as headers
    df = pd.read_csv(csv_path, skiprows=6)
    
    # Define the metrics we want to store
    metrics = [
        "totalEggs", "totalLarvae", "totalPupae", "totalIHbees", 
        "totalForagers", "totalIHbees + totalForagers", 
        "totalDroneEggs", "totalDroneLarvae", "totalDronePupae", "totalDrones"
    ]
    
    # Store each metric as a separate record
    for metric in metrics:
        if metric in df.columns:
            # Convert the column to numpy array
            timeseries_array = df[metric].values.astype(np.float64)
            
            # Handle NaN values
            timeseries_array = np.nan_to_num(timeseries_array, nan=0.0)
            
            # Pickle the array
            timeseries_blob = pickle.dumps(timeseries_array)
            
            # Create database record
            bee_pop_record = BeePopulation(
                metric_name=metric,
                timeseries=timeseries_blob
            )
            
            session.add(bee_pop_record)
            print(f"Added {metric}: {len(timeseries_array)} time points")
    
    session.commit()
    print("Bee population data loading completed!")

if __name__ == "__main__":
    # Test loading
    session = next(get_session())
    try:
        load_bee_population_to_db("data/output.csv", session)
    finally:
        session.close()
