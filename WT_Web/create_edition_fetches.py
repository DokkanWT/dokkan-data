import json
import os
import shutil
import sys
from pathlib import Path

"""
Archive World Tournament edition data from instances to older_editions.
Transfers database, metadata, and first/last fetch files.
"""


def find_fetch_files(fetches_dir):
    """Find all fetch files in the directory and return their paths sorted by number."""
    fetch_files = []

    for file in os.listdir(fetches_dir):
        if file.startswith("fetch") and file.endswith(".json"):
            try:
                # Extract the number from fetchX.json
                number = int(file[5:-5])  # Remove 'fetch' prefix and '.json' suffix
                fetch_files.append((number, os.path.join(fetches_dir, file)))
            except ValueError:
                continue

    # Sort by the fetch number
    fetch_files.sort(key=lambda x: x[0])
    return [path for _, path in fetch_files]


def archive_edition(edition, region):
    """
    Archive an edition from instances/{region} to older_editions/{region}/{edition}.
    
    Transfers:
    - database.db -> {edition}.db
    - metadata.json -> metadata.json
    - fetch1.json -> first.json
    - last fetch -> latest.json
    """
    
    # Get script directory (WT_Web) and parent directory (Dokkan)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(script_dir)
    
    # Define source and destination paths
    instance_dir = os.path.join(parent_dir, "instances", region)
    fetches_dir = os.path.join(instance_dir, "fetches")
    older_editions_dir = os.path.join(parent_dir, "older_editions", region)
    edition_dir = os.path.join(older_editions_dir, str(edition))
    
    # Validate source directory exists
    if not os.path.exists(instance_dir):
        print(f"Error: Instance directory '{instance_dir}' does not exist.")
        return False
    
    if not os.path.exists(fetches_dir):
        print(f"Error: Fetches directory '{fetches_dir}' does not exist.")
        return False
    
    # Find all fetch files
    fetch_files = find_fetch_files(fetches_dir)
    
    if not fetch_files:
        print(f"Error: No fetch files found in '{fetches_dir}'")
        return False
    
    print(f"Found {len(fetch_files)} fetch files")
    print(f"First fetch: {os.path.basename(fetch_files[0])}")
    print(f"Last fetch: {os.path.basename(fetch_files[-1])}")
    
    # Create destination directory
    os.makedirs(edition_dir, exist_ok=True)
    print(f"\nArchiving edition {edition} ({region}) to: {edition_dir}")
    
    # Copy first fetch (fetch1.json)
    first_fetch_src = fetch_files[1]  # fetch1.json represents the WT start time
    first_fetch_dst = os.path.join(edition_dir, "first.json")
    shutil.copy2(first_fetch_src, first_fetch_dst)
    print(f"✓ Copied first fetch: {os.path.basename(first_fetch_src)} -> first.json")
    
    # Copy last fetch
    last_fetch_src = fetch_files[-1]
    last_fetch_dst = os.path.join(edition_dir, "latest.json")
    shutil.copy2(last_fetch_src, last_fetch_dst)
    print(f"✓ Copied last fetch: {os.path.basename(last_fetch_src)} -> latest.json")
    
    # Copy database
    db_src = os.path.join(instance_dir, "database.db")
    db_dst = os.path.join(edition_dir, f"{edition}.db")
    
    if os.path.exists(db_src):
        shutil.copy2(db_src, db_dst)
        print(f"✓ Copied database: database.db -> {edition}.db")
    else:
        print(f"✗ Warning: Database file not found at {db_src}")
    
    # Copy metadata.json
    metadata_src = os.path.join(instance_dir, "metadata.json")
    metadata_dst = os.path.join(edition_dir, "metadata.json")
    
    if os.path.exists(metadata_src):
        shutil.copy2(metadata_src, metadata_dst)
        print(f"✓ Copied metadata: metadata.json")
    else:
        print(f"✗ Warning: metadata.json not found at {metadata_src}")
    
    print(f"\n✓ Edition {edition} ({region}) archived successfully!")
    print(f"  Location: {edition_dir}")
    
    return True


def main():
    if len(sys.argv) != 3:
        print("Usage: python create_edition_fetches.py <edition_number> <region>")
        print("Example: python create_edition_fetches.py 60 GLB")
        print("         python create_edition_fetches.py 57 JP")
        print("\nThis will archive data from instances/{region} to older_editions/{region}/{edition}")
        sys.exit(1)
    
    edition = sys.argv[1]
    region = sys.argv[2].upper()
    
    # Validate region
    if region not in ["GLB", "JP"]:
        print(f"Error: Region must be 'GLB' or 'JP', got '{region}'")
        sys.exit(1)
    
    # Validate edition number
    try:
        edition = int(edition)
    except ValueError:
        print("Error: Edition number must be an integer")
        sys.exit(1)
    
    success = archive_edition(edition, region)
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
