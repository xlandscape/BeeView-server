#!/usr/bin/env python3
"""
Database Management Utility for BeeForage Server
Provides easy controls for database reset and server startup
"""

import os
import subprocess
import sys

def print_banner():
    print("BeeForage Database Management")
    print("=============================")
    print()

def get_current_setting():
    return os.getenv("RESET_DATABASE", "false").lower() == "true"

def set_reset_database(value):
    os.environ["RESET_DATABASE"] = "true" if value else "false"

def delete_database_file():
    """Delete the database file completely"""
    db_file_path = "data/beeview.duckdb"
    if os.path.exists(db_file_path):
        print(f"Deleting database file: {db_file_path}")
        os.remove(db_file_path)
        print("Database file deleted successfully")
        return True
    else:
        print("No database file found to delete")
        return False

def start_server():
    """Start the FastAPI server"""
    try:
        print("Starting BeeForage server...")
        print("   Server will be available at: http://localhost:8000")
        print("   API documentation at: http://localhost:8000/docs")
        print("   Press Ctrl+C to stop the server")
        print()
        
        subprocess.run([
            sys.executable, "-m", "uvicorn", 
            "main:app", "--reload", "--port", "8000"
        ], check=True)
    except KeyboardInterrupt:
        print("\nServer stopped by user")
    except subprocess.CalledProcessError as e:
        print(f"Error starting server: {e}")
        sys.exit(1)

def main():
    print_banner()
    
    current_reset = get_current_setting()
    print(f"Current setting: RESET_DATABASE={'true' if current_reset else 'false'}")
    
    if current_reset:
        print("   → Database will be COMPLETELY RESET on startup (all tables dropped)")
    else:
        print("   → Only data will be cleared on startup (tables preserved)")
    
    print()
    print("Options:")
    print("1. Delete database file - Completely remove database file")
    print("2. Enable table reset - Set server to recreate all tables on startup")
    print("3. Disable table reset - Set server to only clear data on startup")
    print("4. Start server - Start server with current setting")
    print("5. Show info - Show database info")
    print("6. Exit")
    print()
    
    try:
        choice = input("Choose option (1-6): ").strip()
        
        if choice == "1":
            delete_database_file()
            print("Database file deleted. Server will create fresh database on startup.")
            input("Press Enter to continue or Ctrl+C to exit...")
            start_server()
            
        elif choice == "2":
            set_reset_database(True)
            print("Enabled complete database reset")
            print("Server will recreate all tables on next startup")
            input("Press Enter to start server or Ctrl+C to cancel...")
            start_server()
            
        elif choice == "3":
            set_reset_database(False)
            print("Disabled complete database reset")
            print("Server will only clear data, preserving table structure")
            input("Press Enter to start server or Ctrl+C to cancel...")
            start_server()
            
        elif choice == "4":
            start_server()
            
        elif choice == "5":
            print("\nDatabase Information:")
            print(f"   Database file: data/beeview.duckdb")
            print(f"   File exists: {os.path.exists('data/beeview.duckdb')}")
            print(f"   Reset mode: {'COMPLETE RESET' if current_reset else 'DATA CLEARING'}")
            print(f"   Tables: features, nectar, pollen")
            print(f"   Environment variable: RESET_DATABASE={os.getenv('RESET_DATABASE', 'false')}")
            
        elif choice == "6":
            print("Goodbye!")
            
        else:
            print("Invalid option")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\nCancelled by user")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
