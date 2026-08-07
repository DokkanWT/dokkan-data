#!/usr/bin/env python3
"""
Script to sort fetch files by their rank1000_updated_at timestamp
and rename them to fetch0.json, fetch1.json, etc. in chronological order.
Also removes duplicates by comparing the top 1000 players' timestamps.
"""

import argparse
import json
import os
import shutil
from pathlib import Path


def get_top_1000_signature(data):
    """Extract timestamps from top 1000 players to create a signature for duplicate detection"""
    players = data.get("players", [])
    # Get up to 1000 players' points (timestamps)
    timestamps = tuple(player.get("points") for player in players[:1000])
    return timestamps


def sort_and_rename_fetches(fetch_dir):
    """Sort fetch files by timestamp, remove duplicates, and rename them in order"""
    
    fetch_path = Path(fetch_dir)
    
    if not fetch_path.exists():
        print(f"Error: Directory {fetch_dir} does not exist")
        return
    
    # Find all JSON files in the directory (excluding config.json)
    fetch_files = []
    for file in fetch_path.glob("*.json"):
        if file.name == "config.json":
            continue
        
        try:
            with open(file, 'r') as f:
                data = json.load(f)
                timestamp = data.get("rank1000_updated_at")
                
                if timestamp is not None:
                    # Get signature for duplicate detection
                    signature = get_top_1000_signature(data)
                    
                    fetch_files.append({
                        "path": file,
                        "timestamp": timestamp,
                        "name": file.name,
                        "signature": signature
                    })
                else:
                    print(f"Warning: {file.name} has no rank1000_updated_at field, skipping")
        except Exception as e:
            print(f"Error reading {file.name}: {e}")
    
    if not fetch_files:
        print("No fetch files found to sort")
        return
    
    # Sort by timestamp
    fetch_files.sort(key=lambda x: x["timestamp"])
    
    # Remove duplicates by comparing signatures
    unique_fetches = []
    duplicate_files = []
    seen_signatures = set()
    duplicates_removed = 0
    
    for fetch in fetch_files:
        if fetch["signature"] not in seen_signatures:
            seen_signatures.add(fetch["signature"])
            unique_fetches.append(fetch)
        else:
            duplicates_removed += 1
            duplicate_files.append(fetch)
            print(f"  Duplicate found: {fetch['name']} (same top 1000 as another fetch)")
    
    fetch_files = unique_fetches
    
    if duplicates_removed > 0:
        print(f"\nRemoved {duplicates_removed} duplicate(s)")
    else:
        print("\nNo duplicates found")
    
    print(f"Found {len(fetch_files)} fetch files to sort")
    print("\nSorted order:")
    for i, fetch in enumerate(fetch_files):
        from datetime import datetime
        dt = datetime.fromtimestamp(fetch["timestamp"])
        print(f"  {i}: {fetch['name']} -> fetch{i}.json (timestamp: {dt})")
    
    # Create a temporary directory for renaming
    temp_dir = fetch_path / ".temp_sort"
    temp_dir.mkdir(exist_ok=True)
    
    try:
        # First, delete duplicate files
        for dup in duplicate_files:
            dup["path"].unlink()
            print(f"  Deleted duplicate: {dup['name']}")
        
        # Move all files to temp directory with new names
        for i, fetch in enumerate(fetch_files):
            temp_file = temp_dir / f"fetch{i}.json"
            shutil.copy2(fetch["path"], temp_file)
        
        # Delete original fetch files (but not config.json)
        for fetch in fetch_files:
            fetch["path"].unlink()
        
        # Move renamed files back to original directory
        for temp_file in temp_dir.glob("fetch*.json"):
            shutil.move(str(temp_file), str(fetch_path / temp_file.name))
        
        # Clean up temp directory
        temp_dir.rmdir()
        
        print(f"\nSuccessfully sorted and renamed {len(fetch_files)} files!")
        
        # Update config.json with new LAST_FETCH count
        config_file = fetch_path / "config.json"
        if config_file.exists():
            try:
                with open(config_file, 'r') as f:
                    config = json.load(f)
                config["LAST_FETCH"] = len(fetch_files)
                with open(config_file, 'w') as f:
                    json.dump(config, f, indent=4)
                print(f"Updated config.json: LAST_FETCH = {len(fetch_files)}")
            except Exception as e:
                print(f"Warning: Could not update config.json: {e}")
        
    except Exception as e:
        print(f"Error during renaming: {e}")
        print("Attempting to restore from temp directory...")
        
        # Try to restore original files
        for temp_file in temp_dir.glob("*.json"):
            try:
                shutil.move(str(temp_file), str(fetch_path))
            except Exception:
                pass
        
        try:
            temp_dir.rmdir()
        except Exception:
            pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Sort fetch files by timestamp and rename them sequentially"
    )
    parser.add_argument(
        "fetch_dir",
        nargs="?",
        default=None,
        help="Path to the fetches directory"
    )
    parser.add_argument(
        "--GLB",
        action="store_const",
        const="GLB",
        dest="region",
        help="Use GLB fetches directory"
    )
    parser.add_argument(
        "--JP",
        action="store_const",
        const="JP",
        dest="region",
        help="Use JP fetches directory"
    )
    
    args = parser.parse_args()
    
    # Determine fetch directory
    if args.fetch_dir:
        fetch_dir = args.fetch_dir
    elif args.region:
        fetch_dir = f"instances/{args.region}/fetches"
    else:
        fetch_dir = "instances/GLB/fetches"
    
    print(f"Sorting fetches in: {fetch_dir}")
    sort_and_rename_fetches(fetch_dir)
