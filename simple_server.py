#!/usr/bin/env python3

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify actual origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/applications")
def get_applications(feature_ids: str = None):
    """
    Get plant protection product application data
    
    Args:
        feature_ids: Optional comma-separated list of feature IDs to filter by
    
    Returns:
        JSON with applications data
    """
    try:
        applications_file = "data/applications.txt"
        if not os.path.exists(applications_file):
            return {"applications": [], "message": "Applications data file not found"}
        
        # Read and parse the applications file
        applications = []
        with open(applications_file, 'r') as f:
            lines = f.readlines()
        
        # Skip header line
        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue
                
            parts = line.split(',')
            if len(parts) >= 5:
                try:
                    application = {
                        "lulc_feature_id": int(parts[0]),
                        "application_day": int(parts[1]),
                        "conc_nectar": float(parts[2]),
                        "conc_pollen": float(parts[3]),
                        "contact": float(parts[4])
                    }
                    applications.append(application)
                except (ValueError, IndexError) as e:
                    # Skip malformed lines
                    continue
        
        # Filter by feature IDs if provided
        if feature_ids:
            try:
                feature_id_list = [int(fid.strip()) for fid in feature_ids.split(',')]
                applications = [app for app in applications if app["lulc_feature_id"] in feature_id_list]
            except ValueError:
                return {"error": "Invalid feature_ids parameter"}
        
        return {"applications": applications}
        
    except Exception as e:
        print(f"Error reading applications data: {e}")
        return {"applications": [], "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    print("Starting simple applications server on http://localhost:8001")
    print("This server only serves the applications endpoint for testing")
    uvicorn.run(app, host="0.0.0.0", port=8001)