import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

import requests
from config import BOTS, USER_AGENT, WT_EDITION


def get_region_config(region):
    if region is None:
        region = "GLB"
    region_key = str(region).upper()
    if region_key not in BOTS:
        raise ValueError(f"Invalid region: {region}. Expected 'GLB' or 'JP'.")
    return BOTS[region_key]


LOCKED = "Database if locked chef you cannot access it"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
output_dir = os.path.join(BASE_DIR, "../top100_data")
if not os.path.exists(output_dir):
    os.makedirs(output_dir)


def load_db_data(region="GLB"):
    region_cfg = get_region_config(region)
    path = region_cfg["DB_PATH"]
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    print(f"Trying to look at {path}")
    return conn


def find_rank(conn, rank, region="GLB"):
    cursor = conn.cursor()
    update, start, end, total, left, elapsed = time_data(region=region)
    elapsed_hours = round(elapsed.total_seconds() / 3600, 2)
    conn.create_function("strrev", 1, lambda s: s[::-1])
    cursor.execute(
        """
        SELECT id FROM players WHERE
        CAST(SUBSTR(hour, LENGTH(hour) - INSTR(strrev(hour), ',') + 2, LENGTH(hour)) AS FLOAT) = ?
            AND
        CAST(SUBSTR(ranks, LENGTH(ranks) - INSTR(strrev(ranks), ',') + 2, LENGTH(ranks)) AS INTEGER) = ?
    """,
        (elapsed_hours, rank),
    )
    row = cursor.fetchone()
    if row is not None:
        print(f"Found rank {rank} in {region} database id: {row[0]}")
        return row[0]
    if not row:
        return None


# You might think that we need to pass the region here but we don't because we are already passing the right database in the parameter
def find_player(conn, identifier):
    try:
        cursor = conn.cursor()

        # Try searching by ID
        cursor.execute("SELECT * FROM players WHERE id = ?", (identifier,))
        row = cursor.fetchone()
        if row:
            return format_player(cursor, row)

        # Try exact name match
        cursor.execute("SELECT * FROM players WHERE name = ?", (identifier,))
        exact_rows = cursor.fetchall()
        if exact_rows:
            return (
                [format_player(cursor, r) for r in exact_rows]
                if len(exact_rows) > 1
                else format_player(cursor, exact_rows[0])
            )

        # Try partial name match
        search_pattern = f"%{identifier}%"
        cursor.execute("SELECT * FROM players WHERE name LIKE ?", (search_pattern,))
        rows = cursor.fetchall()
        if rows:
            return (
                [format_player(cursor, r) for r in rows]
                if len(rows) > 1
                else format_player(cursor, rows[0])
            )

        return None  # No players found
    except sqlite3.OperationalError:
        return LOCKED


def format_player(cursor, row, border=False):
    player = {
        description[0]: value for description, value in zip(cursor.description, row)
    }

    json_fields = [
        "wins",
        "points",
        "hour",
        "points_pace",
        "wins_pace",
        "points_wins",
        "max_points",
        "max_wins",
    ]

    if not border:
        json_fields.append("ranks")

    for field in json_fields:
        if field in player and player[field] is not None:
            try:
                player[field] = json.loads(player[field])
            except json.JSONDecodeError:
                print(f"Error decoding JSON for field {field}. Value: {player[field]}")

    return player


def find_borders(conn, rank):
    cursor = conn.cursor()

    if rank == "all":
        cursor.execute("SELECT * FROM borders")
        rows = cursor.fetchall()
    else:
        cursor.execute("SELECT * FROM borders WHERE rank = ?", (rank,))
        rows = cursor.fetchall()

    if not rows:
        return []

    players = []
    json_fields = [
        "wins",
        "points",
        "hour",
        "points_pace",
        "wins_pace",
        "points_wins",
        "max_points",
        "max_wins",
    ]

    for row in rows:
        player = {
            description[0]: value for description, value in zip(cursor.description, row)
        }
        for field in json_fields:
            if field in player and player[field] is not None:
                try:
                    player[field] = json.loads(player[field])
                except json.JSONDecodeError:
                    print(
                        f"Error decoding JSON for field {field}. Value: {player[field]}"
                    )
        players.append(player)

    return players


def find_gap(main_player, conn):
    last_hour = main_player["hour"][-1]
    last_rank = main_player["ranks"][-1]
    cursor = conn.cursor()
    conn.create_function("strrev", 1, lambda s: s[::-1])
    cursor.execute(
        """
        SELECT id FROM players WHERE
        CAST(SUBSTR(hour, LENGTH(hour) - INSTR(strrev(hour), ',') + 2, LENGTH(hour)) AS FLOAT) = ?
            AND
        CAST(SUBSTR(ranks, LENGTH(ranks) - INSTR(strrev(ranks), ',') + 2, LENGTH(ranks)) AS INTEGER) = ?
    """,
        (last_hour, last_rank + 1),
    )
    row = cursor.fetchone()
    if row is None:
        bottom = None
    else:
        bottom_id = row[0]
        bottom = find_player(conn, bottom_id)

    cursor.execute(
        """
        SELECT id FROM players WHERE
        CAST(SUBSTR(hour, LENGTH(hour) - INSTR(strrev(hour), ',') + 2, LENGTH(hour)) AS FLOAT) = ?
            AND
        CAST(SUBSTR(ranks, LENGTH(ranks) - INSTR(strrev(ranks), ',') + 2, LENGTH(ranks)) AS INTEGER) = ?
    """,
        (last_hour, last_rank - 1),
    )
    row = cursor.fetchone()
    if row is None:
        top = None
    else:
        top_id = row[0]
        top = find_player(conn, top_id)

    return top, bottom


def load_discord_users():
    path = os.path.join(BASE_DIR, "../discord_users.json")
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump({}, f)
    with open(path, "r") as f:
        return json.load(f)


def save_discord_users(discord_users):
    path = os.path.join(BASE_DIR, "../discord_users.json")
    with open(path, "w") as f:
        json.dump(discord_users, f, indent=5)


def latest_fetch(edition_dir=None, region="GLB"):
    region_cfg = get_region_config(region)
    if edition_dir:
        output_dir = os.path.join(
            BASE_DIR,
            "../older_editions",
            region.upper(),
            str(edition_dir),
        )
        latest_file = os.path.join(output_dir, f"latest.json")
        return latest_file if os.path.exists(latest_file) else None
    else:
        output_dir = region_cfg["FETCH_PATH"]
        i = 0
        while True:
            filename = f"fetch{i}.json"
            if not os.path.exists(os.path.join(output_dir, filename)):
                break
            i += 1
        latest_file = os.path.join(output_dir, f"fetch{i-1}.json")
        return latest_file if os.path.exists(latest_file) else None


def first_fetch(edition_dir=None, region="GLB"):
    region_cfg = get_region_config(region)
    if edition_dir:
        # For older editions, look for the first.json file directly
        output_dir = os.path.join(
            BASE_DIR,
            "../older_editions",
            region.upper(),
            str(edition_dir),
        )
        # Prefer metadata.json for older editions (created by fetch_and_save)
        metadata_path = os.path.join(output_dir, "metadata.json")
        return metadata_path if os.path.exists(metadata_path) else None
        
        # The lion cannot be bothered to rename the files so he made a fallback
        for i in range(10):  # Ehh I guess the first valid fetch is there idfk what I'm doing
            fallback_path = os.path.join(output_dir, f"fetch{i}.json")
            if os.path.exists(fallback_path):
                try:
                    with open(fallback_path, "r") as file:
                        data = json.load(file)
                        # Check if this fetch has players (tournament has started)
                        if data.get("players") and len(data["players"]) > 0:
                            return fallback_path
                except (json.JSONDecodeError, KeyError):
                    continue
        
        return None
    else:
        # For current tournament, prefer instances/<region>/metadata.json
        output_dir = region_cfg["FETCH_PATH"]
        instances_path = os.path.dirname(output_dir)
        metadata_path = os.path.join(instances_path, "metadata.json")
        return metadata_path if os.path.exists(metadata_path) else None


def find_best(player_id, region="GLB"):
    """
    Find the edition where the given player achieved their highest latest points.
    
    Args:
        player_id: The player ID to search for
        region: Region to search in ("GLB" or "JP")
    
    Returns:
        dict: Player data from the edition with highest latest points, or None if not found
    """
    region = region.upper()
    older_editions_path = os.path.join(BASE_DIR, "../older_editions", region)
    
    if not os.path.exists(older_editions_path):
        return None
    
    best_player = None
    best_points = -1
    best_edition = None
    
    # Iterate through all edition directories
    for edition_dir in os.listdir(older_editions_path):
        edition_path = os.path.join(older_editions_path, edition_dir)
        if not os.path.isdir(edition_path):
            continue
            
        db_path = os.path.join(edition_path, f"{edition_dir}.db")
        if not os.path.exists(db_path):
            continue
            
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            cursor = conn.cursor()
            
            # Find the player in this edition's database
            cursor.execute("SELECT * FROM players WHERE id = ?", (player_id,))
            row = cursor.fetchone()
            
            if row:
                player = format_player(cursor, row)
                
                # Get the latest points (last element in points array)
                if player.get('points') and len(player['points']) > 0:
                    latest_points = player['points'][-1]
                    
                    if latest_points > best_points:
                        best_points = latest_points
                        best_player = player
                        best_edition = edition_dir
            
            conn.close()
            
        except (sqlite3.Error, json.JSONDecodeError) as e:
            print(f"Error processing edition {edition_dir}: {e}")
            continue
    
    if best_player:
        best_player['edition'] = best_edition
    
    return best_player


def time_data(update_only=True, tournament_over=False, edition_dir=None, region="GLB"):
    region_cfg = get_region_config(region)
    tz = region_cfg["TIMEZONE"] if region_cfg else timezone.utc
    # Prefer metadata.json as the single source of truth for start/end/update
    try:
        if edition_dir:
            # Look for older edition metadata file
            metadata_path = os.path.join(
                BASE_DIR, "../older_editions", region.upper(), str(edition_dir), "metadata.json"
            )
            if not os.path.exists(metadata_path):
                # No metadata for older edition
                return None, None, None, None, None, None
        else:
            # Current tournament metadata in instances/<region>/metadata.json
            instances_path = os.path.dirname(region_cfg["FETCH_PATH"])
            metadata_path = os.path.join(instances_path, "metadata.json")

        if os.path.exists(metadata_path):
            with open(metadata_path, "r") as mf:
                meta = json.load(mf)

            # Use metadata values if present
            start_ts = meta.get("start_at")
            end_ts = meta.get("end_at")
            # prefer explicit rank1000_updated_at; fall back to latest_update
            update_ts = meta.get("rank1000_updated_at") or meta.get("latest_update") or meta.get("rank10000_updated_at")

            start = (
                datetime.utcfromtimestamp(start_ts).replace(tzinfo=timezone.utc).astimezone(tz)
            ) if start_ts is not None else None

            end = (
                datetime.utcfromtimestamp(end_ts).replace(tzinfo=timezone.utc).astimezone(tz)
            ) if end_ts is not None else None

            update = (
                datetime.utcfromtimestamp(update_ts).replace(tzinfo=timezone.utc).astimezone(tz)
            ) if update_ts is not None else None

            total = (end - start) if (start is not None and end is not None) else None
            left = (end - update) if (end is not None and update is not None) else None
            elapsed = (update - start) if (start is not None and update is not None) else None

            return update, start, end, total, left, elapsed

        # If metadata missing for current tournament, fall back to API + latest fetch
        if not edition_dir:
            latest_fetch_path = latest_fetch(None, region)
            if not latest_fetch_path:
                return None, None, None, None, None, None

            with open(latest_fetch_path, "r") as file:
                data = json.load(file)

            headers = {"User-Agent": region_cfg["USER_AGENT"]}
            ping = requests.get(
                f"{region_cfg['API_BASE_URL']}/api/budokai/{region_cfg['WT_EDITION']}",
                headers=headers,
            )
            ping.raise_for_status()
            start_end = ping.json()

            start = (
                datetime.utcfromtimestamp(start_end["start_at"]).replace(tzinfo=timezone.utc).astimezone(tz)
            )
            end = (
                datetime.utcfromtimestamp(start_end["end_at"]).replace(tzinfo=timezone.utc).astimezone(tz)
            )
            update = (
                datetime.utcfromtimestamp(data["rank1000_updated_at"]).replace(tzinfo=timezone.utc).astimezone(tz)
            )
            total = end - start
            left = end - update
            elapsed = update - start
            return update, start, end, total, left, elapsed

        # If edition_dir and metadata missing, return Nones
        return None, None, None, None, None, None
    except Exception:
        return None, None, None, None, None, None
