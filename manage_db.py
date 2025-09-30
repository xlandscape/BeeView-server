#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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

# Environment variable functions removed - using direct file management instead

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
        print("   Server will be available at: http://localhost:32000")
        print("   API documentation at: http://localhost:32000/docs")
        print("   Press Ctrl+C to stop the server")
        print()
        
        subprocess.run([
            sys.executable, "-m", "uvicorn", 
            "main:app", "--reload", "--port", "32000"
        ], check=True)
    except KeyboardInterrupt:
        print("\nServer stopped by user")
    except subprocess.CalledProcessError as e:
        print(f"Error starting server: {e}")
        sys.exit(1)

def show_database_info():
    """Show current database information"""
    db_file_path = "data/beeview.duckdb"
    db_exists = os.path.exists(db_file_path)
    
    print("\nDatabase Information:")
    print("=" * 40)
    print(f"Database file: {db_file_path}")
    print(f"File exists: {'Yes' if db_exists else 'No'}")
    
    if db_exists:
        try:
            # Get file size
            file_size = os.path.getsize(db_file_path)
            size_mb = file_size / (1024 * 1024)
            print(f"File size: {size_mb:.1f} MB")
            
            # Try to connect and get table info
            from sqlalchemy import create_engine, text
            engine = create_engine(f"duckdb:///{db_file_path}")
            
            with engine.connect() as conn:
                # Get table counts
                tables = ['features', 'nectar', 'pollen', 'bee_population', 'vegetation']
                for table in tables:
                    try:
                        result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                        count = result.scalar()
                        print(f"Table '{table}': {count:,} records")
                    except Exception:
                        print(f"Table '{table}': Not accessible or doesn't exist")
                        
        except Exception as e:
            print(f"Could not read database details: {e}")
    
    print("=" * 40)

def main():
    print_banner()
    
    db_file_path = "data/beeview.duckdb"
    db_exists = os.path.exists(db_file_path)
    
    if db_exists:
        print(f"[OK] Database found: {db_file_path}")
        print("     Server will use existing data unless you choose to delete and reload.")
    else:
        print(f"[--] No database found: {db_file_path}")
        print("     Server will create fresh database and load all data on startup.")
    
    print()
    print("Options:")
    print("1. Delete database and reload - Remove existing data and load fresh")
    print("2. Run server as-is - Use existing database or create if missing")
    print("3. Show database info - Display detailed database information")
    print("4. Exit")
    print()
    
    try:
        choice = input("Choose option (1-4): ").strip()
        
        if choice == "1":
            if db_exists:
                print(f"\nDeleting database file: {db_file_path}")
                os.remove(db_file_path)
                print("Database deleted successfully")
            else:
                print("\nNo database file to delete")
            
            print("\nStarting server (will load fresh data)...")
            print("   Server will start at: http://localhost:32000")
            print("   API documentation at: http://localhost:32000/docs")
            print("   Press Ctrl+C to stop the server\n")
            
            start_server()
            
        elif choice == "2":
            if db_exists:
                print("\nStarting server with existing database...")
            else:
                print("\nStarting server (will create and load fresh database)...")
            
            print("   Server will start at: http://localhost:32000")
            print("   API documentation at: http://localhost:32000/docs")
            print("   Press Ctrl+C to stop the server\n")
            
            start_server()
            
        elif choice == "3":
            show_database_info()
            input("\nPress Enter to return to menu...")
            main()  # Return to main menu
            
        elif choice == "4":
            print("Goodbye!")
            
        else:
            print("Invalid option")
            main()  # Return to main menu
            
    except KeyboardInterrupt:
        print("\nCancelled by user")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
