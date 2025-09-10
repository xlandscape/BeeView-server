#!/usr/bin/env python3
"""
Load bee population data from output.csv into the database
"""

import pandas as pd
import pickle
import numpy as np
from sqlalchemy.orm import Session
from models import Feature, BeePopulation
from database import get_session

def load_bee_population_to_db(csv_path: str, session: Session):
    """
    Load bee population data from CSV file into the database
    
    Args:
        csv_path: Path to the output.csv file
        session: Database session
    """
    print(f"LOADING BEE POPULATION: Loading bee population data from {csv_path}")
    
    # Read CSV file, skipping first 6 rows, using row 7 as headers
    df = pd.read_csv(csv_path, skiprows=6)
    
    print(f"   Loaded {len(df)} rows of bee population data")
    
    # Extract the columns we need
    bee_columns = [
        "day", "totalEggs", "totalLarvae", "totalPupae", "totalIHbees", 
        "totalForagers", "totalIHbees + totalForagers", "totalDroneEggs", 
        "totalDroneLarvae", "totalDronePupae", "totalDrones"
    ]
    
    # Check if all required columns exist
    missing_columns = [col for col in bee_columns if col not in df.columns]
    if missing_columns:
        raise ValueError(f"Missing required columns in CSV: {missing_columns}")
    
    # Extract bee data
    bee_data = df[bee_columns].copy()
    
    # Sort by day to ensure proper time series order
    bee_data = bee_data.sort_values('day').reset_index(drop=True)
    
    print(f"   Bee population data spans {bee_data['day'].min()} to {bee_data['day'].max()} days")
    
    # Get all features (assuming we want to apply the same bee population data to all features)
    # In a real scenario, you might want different bee populations per feature
    features = session.query(Feature).all()
    
    if not features:
        print("   Warning: No features found in database. Bee population data will not be loaded.")
        return
        
    print(f"   Applying bee population data to {len(features)} features")
    
    # Create the time series data for each metric (excluding 'day')
    metrics = [col for col in bee_columns if col != "day"]
    
    # Build time series dict
    timeseries_data = {}
    for metric in metrics:
        # Convert to numpy array and ensure proper data type
        values = bee_data[metric].astype(float).values
        timeseries_data[metric] = values.tolist()  # Convert to list for JSON serialization
    
    # Add day information for reference
    timeseries_data['days'] = bee_data['day'].astype(int).values.tolist()
    
    print(f"   Created time series for metrics: {', '.join(metrics)}")
    
    # Serialize the time series data
    pickled_timeseries = pickle.dumps(timeseries_data)
    
    # Remove existing bee population data
    session.query(BeePopulation).delete()
    
    # Add bee population data for each feature
    bee_population_entries = []
    for feature in features:
        bee_pop = BeePopulation(
            feature_id=feature.id,
            timeseries=pickled_timeseries
        )
        bee_population_entries.append(bee_pop)
    
    # Bulk insert
    session.add_all(bee_population_entries)
    session.commit()
    
    print(f"   Successfully loaded bee population data for {len(bee_population_entries)} features")
    print(f"   Metrics available: {', '.join(metrics)}")

if __name__ == "__main__":
    # Test loading
    session = next(get_session())
    try:
        load_bee_population_to_db("data/output.csv", session)
    finally:
        session.close()
