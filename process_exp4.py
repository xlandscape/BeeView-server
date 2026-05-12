#!/usr/bin/env python3
import os
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from collections import defaultdict

# Base path
experiments_dir = Path("experiments")

# Step 1: Scan for exp4_*_hive<HH>_mc<MM>__* folders
pattern = re.compile(r'exp4_(.+?)_hive(\d+)_mc(\d+)__')

exp4_folders = {}  # {(hive_id, base): [(mc_num, folder_path), ...]}
hive_info = defaultdict(lambda: {"sources": set(), "base": None})

for folder in sorted(experiments_dir.glob("exp4_*")):
    match = pattern.match(folder.name)
    if match:
        base = match.group(1)
        hive_id = match.group(2)
        mc_num = int(match.group(3))
        
        key = (hive_id, base)
        if key not in exp4_folders:
            exp4_folders[key] = []
        
        exp4_folders[key].append((mc_num, folder))
        hive_info[hive_id]["base"] = base
        hive_info[hive_id]["sources"].add(folder)

# Sort by mc_num for each hive
for key in exp4_folders:
    exp4_folders[key].sort(key=lambda x: x[0])

print(f"Found {len(exp4_folders)} hive groups with exp4 data")

# Step 2-4: Create destination folders and copy MC folders
results = []

for (hive_id, base), mc_folders in sorted(exp4_folders.items()):
    dest_name = f"exp4_{base}_hive{hive_id}"
    dest_path = experiments_dir / dest_name
    dest_mcs = dest_path / "mcs"
    
    # Create destination folder
    dest_path.mkdir(exist_ok=True)
    dest_mcs.mkdir(exist_ok=True)
    
    num_source_runs = len(mc_folders)
    num_copied_mcs = 0
    user_xml_exists = False
    
    # Copy MC folders from all sources
    for mc_num, src_folder in mc_folders:
        src_mcs = src_folder / "mcs"
        if src_mcs.exists():
            for mc_subfolder in src_mcs.iterdir():
                if mc_subfolder.is_dir():
                    dest_mc_path = dest_mcs / mc_subfolder.name
                    if not dest_mc_path.exists():
                        shutil.copytree(mc_subfolder, dest_mc_path)
                        num_copied_mcs += 1
    
    # Copy user.xml from mc0__ if available, otherwise from first available
    user_xml_source = None
    for mc_num, src_folder in mc_folders:
        src_user_xml = src_folder / "user.xml"
        if src_user_xml.exists():
            if mc_num == 0:  # Prefer mc0__
                user_xml_source = src_user_xml
                break
            elif user_xml_source is None:
                user_xml_source = src_user_xml
    
    if user_xml_source:
        dest_user_xml = dest_path / "user.xml"
        shutil.copy2(user_xml_source, dest_user_xml)
        user_xml_exists = True
        
        # Update SimID to just hive<HH>
        tree = ET.parse(dest_user_xml)
        root = tree.getroot()
        sim_id_elem = root.find("SimID")
        if sim_id_elem is not None:
            sim_id_elem.text = f"hive{hive_id}"
            tree.write(dest_user_xml, encoding="utf-8", xml_declaration=True)
    
    results.append({
        "hive": hive_id,
        "folder": dest_name,
        "num_source_runs": num_source_runs,
        "num_copied_mcs": num_copied_mcs,
        "user_xml": "Yes" if user_xml_exists else "No"
    })

# Step 5: Print verification table
print("\n" + "="*80)
print("VERIFICATION TABLE - Destination Folders")
print("="*80)
print(f"{'Hive':<6} {'Folder':<35} {'Sources':<8} {'MCs':<6} {'user.xml':<10}")
print("-"*80)
for result in sorted(results, key=lambda x: x["hive"]):
    print(f"{result['hive']:<6} {result['folder']:<35} {result['num_source_runs']:<8} {result['num_copied_mcs']:<6} {result['user_xml']:<10}")
print("="*80)

