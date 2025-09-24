import pandas as pd
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from database import get_database_url, Base
from models import LandCoverVegetationMapping


def load_vegetation_mapping(csv_file_path: str):
    """
    Load vegetation mapping data from CSV file into the database.
    
    Args:
        csv_file_path: Path to the land cover to vegetation mapping CSV file
    """
    # Create database engine
    engine = create_engine(get_database_url())
    
    # Create tables if they don't exist
    Base.metadata.create_all(engine)
    
    try:
        # Read CSV file
        df = pd.read_csv(csv_file_path)
        print(f"Loading {len(df)} vegetation mapping records from {csv_file_path}")
        
        # Create database session
        with Session(engine) as session:
            # Clear existing data
            session.query(LandCoverVegetationMapping).delete()
            
            # Load each row
            for _, row in df.iterrows():
                # Handle empty string values as None for nullable fields
                def safe_string(value):
                    if pd.isna(value):
                        return None
                    str_val = str(value).strip()
                    return str_val if str_val else None
                
                data_source = safe_string(row['Data Source'])
                source_code = safe_string(row['Source Code'])
                last_change = safe_string(row['last change'])
                vegetation_certainty = safe_string(row['Vegetation-to-LULC certainty (school quotes)'])
                
                mapping = LandCoverVegetationMapping(
                    l1_code=int(row['L1_code']),
                    l1_label=row['L1_label'],
                    l2_code=int(row['L2_code']),
                    l2_label=row['L2_label'],
                    l3_code=int(row['L3_code']),
                    l3_label=row['L3_label'],
                    data_source=data_source,
                    source_code=source_code,
                    last_change=last_change,
                    vegetation=row['Vegetation'],
                    vegetation_certainty=vegetation_certainty
                )
                session.add(mapping)
                session.flush()  # Flush each record individually
            
            # Commit the transaction
            session.commit()
            print(f"Successfully loaded {len(df)} vegetation mapping records")
            
    except Exception as e:
        print(f"Error loading vegetation mapping data: {e}")
        raise


def get_vegetation_for_l1_label(l1_label: str) -> str:
    """
    Get vegetation type for a given L1_label.
    
    Args:
        l1_label: The L1 land cover label
        
    Returns:
        Vegetation type string, or None if not found
    """
    engine = create_engine(get_database_url())
    
    with Session(engine) as session:
        mapping = session.query(LandCoverVegetationMapping).filter_by(l1_label=l1_label).first()
        if mapping:
            return mapping.vegetation
        return None


if __name__ == "__main__":
    # Default path to the CSV file
    csv_path = os.path.join(os.path.dirname(__file__), "data", "land cover to vegetation default mapping.csv")
    
    if os.path.exists(csv_path):
        load_vegetation_mapping(csv_path)
    else:
        print(f"CSV file not found at: {csv_path}")
        print("Please provide the correct path to the vegetation mapping CSV file.")