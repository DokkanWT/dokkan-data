#!/usr/bin/env python3
"""
Archive the current World Tournament edition into older_editions.

The region is configured with the REGION global below. The edition number is
read from config.py (BOTS[REGION]["WT_EDITION"]).

What it does:
  * Skips if older_editions/<REGION>/<edition> already exists.
  * Finds the first fetch of the tournament (first fetch whose
    rank1000_updated_at >= metadata start_at).
  * Finds the last fetch of the tournament (EARLIEST fetch whose
    rank1000_updated_at >= metadata end_at).
  * Copies those fetches as first.json / latest.json, copies metadata.json,
    and snapshots the live database as <edition>.db.

The live instance data (fetches and database) is left untouched.
"""

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import config

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# "GLB" or "JP" (case-insensitive)
REGION = "GLB"

ROOT_DIR = Path(__file__).resolve().parent

FETCH_FILE_RE = re.compile(r"^fetch(\d+)\.json$")
RANK1000_RE = re.compile(r'"rank1000_updated_at"\s*:\s*(\d+)')


def get_region_settings(region):
    """Return (REGION, region config dict) from config.py."""
    region = str(region).upper()
    if region not in config.BOTS:
        raise ValueError(f"Unknown region {region!r}; expected one of {list(config.BOTS)}")
    return region, config.BOTS[region]


def get_edition(region, region_cfg):
    """Read the WT edition for the region from config.py."""
    edition = region_cfg.get("WT_EDITION")
    if edition is None:
        edition = getattr(config, "WT_EDITION", None)
    if not edition:
        raise ValueError(f"No WT_EDITION configured for {region}")
    return int(edition)


def list_fetches(fetch_dir):
    """Return fetch*.json paths sorted by their numeric suffix."""
    fetches = []
    for path in fetch_dir.iterdir():
        match = FETCH_FILE_RE.match(path.name)
        if match and path.is_file():
            fetches.append((int(match.group(1)), path))
    fetches.sort(key=lambda item: item[0])
    return [path for _, path in fetches]


def read_rank1000_timestamp(path):
    """Read rank1000_updated_at cheaply (without loading the whole fetch)."""
    try:
        with path.open("r", encoding="utf-8") as file:
            head = file.read(4096)
        match = RANK1000_RE.search(head)
        if match:
            return int(match.group(1))
    except OSError:
        return None

    # Fallback for unusually formatted files.
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return None

    value = data.get("rank1000_updated_at")
    return int(value) if value is not None else None


def collect_entries(fetch_files):
    """Build a timestamp-ordered list of (timestamp, fetch index, path)."""
    entries = []
    for index, path in enumerate(fetch_files):
        timestamp = read_rank1000_timestamp(path)
        if timestamp is None:
            print(f"  Warning: {path.name} has no rank1000_updated_at, ignoring it")
            continue
        entries.append((timestamp, index, path))
    entries.sort(key=lambda item: (item[0], item[1]))
    return entries


def pick_first(entries, start_at):
    """First fetch at/after tournament start; earliest fetch as fallback."""
    if start_at is not None:
        for entry in entries:
            if entry[0] >= start_at:
                return entry
    return entries[0]


def pick_last(entries, end_at):
    """Earliest fetch at/after tournament end; final fetch as fallback."""
    if end_at is not None:
        for entry in entries:
            if entry[0] >= end_at:
                return entry
    return entries[-1]


def format_time(timestamp, tz):
    return datetime.fromtimestamp(timestamp, tz=tz).strftime("%Y-%m-%d %H:%M:%S %Z")


def copy_database(source, destination):
    """Take a consistent SQLite snapshot, falling back to a plain file copy."""
    if destination.exists():
        destination.unlink()

    try:
        source_conn = sqlite3.connect(
            f"file:{source.as_posix()}?mode=ro", uri=True, timeout=30
        )
        try:
            dest_conn = sqlite3.connect(str(destination), timeout=30)
            try:
                with dest_conn:
                    source_conn.backup(dest_conn)
            finally:
                dest_conn.close()
        finally:
            source_conn.close()
    except sqlite3.Error as exc:
        print(f"  Warning: SQLite snapshot failed ({exc}); copying file directly")
        if destination.exists():
            destination.unlink()
        shutil.copy2(source, destination)


def archive(region, region_cfg, edition, dry_run=False):
    fetch_dir = Path(os.path.expanduser(region_cfg["FETCH_PATH"]))
    db_path = Path(os.path.expanduser(region_cfg["DB_PATH"]))
    instance_dir = fetch_dir.parent
    metadata_path = instance_dir / "metadata.json"

    edition_dir = ROOT_DIR / "older_editions" / region / str(edition)
    tz = region_cfg.get("TIMEZONE", timezone.utc)

    print(f"Region:  {region}")
    print(f"Edition: {edition}")
    print(f"Target:  {edition_dir}")

    if edition_dir.exists():
        print("Edition already archived - skipping.")
        return 0

    if not fetch_dir.is_dir():
        print(f"Error: fetches directory not found: {fetch_dir}", file=sys.stderr)
        return 1
    if not db_path.is_file():
        print(f"Error: database not found: {db_path}", file=sys.stderr)
        return 1
    if not metadata_path.is_file():
        print(f"Error: metadata not found: {metadata_path}", file=sys.stderr)
        return 1

    try:
        with metadata_path.open("r", encoding="utf-8") as file:
            metadata = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Error: could not read {metadata_path}: {exc}", file=sys.stderr)
        return 1

    start_at = metadata.get("start_at")
    end_at = metadata.get("end_at")
    start_at = int(start_at) if start_at is not None else None
    end_at = int(end_at) if end_at is not None else None

    if start_at is None:
        print("Warning: metadata has no start_at; using the earliest fetch as first")
    if end_at is None:
        print("Warning: metadata has no end_at; using the final fetch as latest")

    fetch_files = list_fetches(fetch_dir)
    if not fetch_files:
        print(f"Error: no fetch*.json files in {fetch_dir}", file=sys.stderr)
        return 1

    entries = collect_entries(fetch_files)
    if not entries:
        print("Error: no fetch has a rank1000_updated_at timestamp", file=sys.stderr)
        return 1

    first_timestamp, _, first_fetch = pick_first(entries, start_at)
    last_timestamp, _, last_fetch = pick_last(entries, end_at)

    print()
    print(f"First fetch:  {first_fetch.name} ({format_time(first_timestamp, tz)})")
    if start_at is not None and first_timestamp < start_at:
        print(f"  Warning: earliest fetch is before start_at ({format_time(start_at, tz)})")
    print(f"Last fetch:   {last_fetch.name} ({format_time(last_timestamp, tz)})")
    if end_at is not None:
        print(f"  Target: earliest fetch with rank1000_updated_at >= end_at ({format_time(end_at, tz)})")
        if last_timestamp < end_at:
            print("  Warning: no fetch is at/after end_at; using the final fetch")
    print(f"Database:     {db_path}")
    print(f"Metadata:     {metadata_path}")

    if dry_run:
        print("\n[dry-run] Nothing was written.")
        return 0

    # Build in a temp directory so an interrupted run cannot leave a partial
    # edition directory that would be skipped on the next attempt.
    temp_dir = edition_dir.parent / f".{edition}.tmp"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True)

    try:
        shutil.copy2(first_fetch, temp_dir / "first.json")
        print(f"\nCopied {first_fetch.name} -> first.json")

        shutil.copy2(last_fetch, temp_dir / "latest.json")
        print(f"Copied {last_fetch.name} -> latest.json")

        shutil.copy2(metadata_path, temp_dir / "metadata.json")
        print("Copied metadata.json -> metadata.json")

        copy_database(db_path, temp_dir / f"{edition}.db")
        print(f"Copied {db_path.name} -> {edition}.db")

        temp_dir.rename(edition_dir)
    except Exception as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        print(f"Error: archiving failed: {exc}", file=sys.stderr)
        return 1

    print(f"\nEdition {edition} ({region}) archived to {edition_dir}")
    print("Live instance data was left untouched.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Archive the current WT edition into older_editions."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show which fetches/database would be archived without writing anything",
    )
    args = parser.parse_args(argv)

    try:
        region, region_cfg = get_region_settings(REGION)
        edition = get_edition(region, region_cfg)
    except (ValueError, KeyError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    return archive(region, region_cfg, edition, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
