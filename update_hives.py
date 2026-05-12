#!/usr/bin/env python3
import os
import re
import subprocess
import sqlite3
from pathlib import Path

# Change to the BeeView-server directory
os.chdir(os.path.expandvars('%USERPROFILE%') + '\\xLandscape\\BeeView-server')

# Find all hive folders
experiments_dir = Path('experiments')
hive_pattern = re.compile(r'exp1_TaG_hive(\d+)$')

hive_folders = sorted([
    d for d in experiments_dir.iterdir()
    if d.is_dir() and hive_pattern.match(d.name)
])

print(f"Found {len(hive_folders)} hive folders to process:\n")

# Process each hive
for hive_path in hive_folders:
    match = hive_pattern.match(hive_path.name)
    if not match:
        continue
    
    hh = match.group(1)
    new_sim_id = f"hive{hh}"
    user_xml_path = hive_path / 'user.xml'
    
    if not user_xml_path.exists():
        print(f"WARNING: {user_xml_path} does not exist, skipping")
        continue
    
    # Read the current content
    with open(user_xml_path, 'r') as f:
        content = f.read()
    
    # Extract the current SimID
    current_match = re.search(r'<SimID>(.*?)</SimID>', content)
    current_sim_id = current_match.group(1) if current_match else "UNKNOWN"
    
    # Replace the SimID
    new_content = re.sub(
        r'<SimID>.*?</SimID>',
        f'<SimID>{new_sim_id}</SimID>',
        content
    )
    
    # Write back if changed
    if new_content != content:
        with open(user_xml_path, 'w') as f:
            f.write(new_content)
        print(f"✓ Updated {hive_path.name}/user.xml")
        print(f"  Old SimID: {current_sim_id}")
        print(f"  New SimID: {new_sim_id}")
    else:
        print(f"- No change needed for {hive_path.name}/user.xml")
    print()

print("\n" + "="*70)
print("Running import_run.py for each hive...")
print("="*70 + "\n")

# Get initial run count
try:
    conn = sqlite3.connect('data/beeview.duckdb')
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM runs")
    initial_count = cursor.fetchone()[0]
    conn.close()
    print(f"Initial run count: {initial_count}\n")
except Exception as e:
    print(f"WARNING: Could not get initial run count: {e}\n")
    initial_count = None

# Run import_run.py for each hive
for hive_path in hive_folders:
    match = hive_pattern.match(hive_path.name)
    if not match:
        continue
    
    hh = match.group(1)
    cmd = f"python import_run.py experiments/exp1_TaG_hive{hh}/ --force"
    print(f"Running: {cmd}")
    
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    
    if result.returncode == 0:
        print(f"✓ Successfully imported hive{hh}")
    else:
        print(f"✗ Error importing hive{hh}")
        if result.stdout:
            print(f"  stdout: {result.stdout[:200]}")
        if result.stderr:
            print(f"  stderr: {result.stderr[:200]}")
    print()

print("\n" + "="*70)
print("Verifying database updates...")
print("="*70 + "\n")

# Get final run count
try:
    conn = sqlite3.connect('data/beeview.duckdb')
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM runs")
    final_count = cursor.fetchone()[0]
    conn.close()
    print(f"Final run count: {final_count}")
    if initial_count is not None:
        print(f"Change: {final_count - initial_count} new runs added")
except Exception as e:
    print(f"ERROR: Could not get final run count: {e}")

print("\nDone!")
