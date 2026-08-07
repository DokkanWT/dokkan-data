import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

from cogs.utils import get_region_config


def find_first_fetch_with_players(fetch_dir):
    """Find the first fetch file that contains actual players"""
    i = 0
    while True:
        filename = f"fetch{i}.json"
        filepath = os.path.join(fetch_dir, filename)
        if not os.path.exists(filepath):
            break

        try:
            with open(filepath, "r") as file:
                data = json.load(file)
                # Check if this fetch has players (tournament has started)
                if data.get("players") and len(data["players"]) > 0:
                    return filepath, data
        except (json.JSONDecodeError, KeyError):
            # Skip invalid files
            pass

        i += 1

    return None, None


def update_data_manual(data_fetch, db_path, region="GLB", start_timestamp=None, is_metadata_start=True):
    """
    Update database using fetch data without calling API.
    Uses fetch files to calculate tournament start time.
    """
    region_cfg = get_region_config(region)
    tz = region_cfg["TIMEZONE"]

    # Get current update timestamp
    update = (
        datetime.utcfromtimestamp(data_fetch["rank1000_updated_at"])
        .replace(tzinfo=timezone.utc)
        .astimezone(tz)
    )

    # Calculate elapsed time using start_timestamp
    if start_timestamp:
        start = (
            datetime.utcfromtimestamp(start_timestamp)
            .replace(tzinfo=timezone.utc)
            .astimezone(tz)
        )
        # Only subtract 15 minutes if timestamp is from first fetch (not from metadata)
        if not is_metadata_start:
            start = start - timedelta(minutes=15)
    else:
        # Fallback if no start timestamp provided
        start = update

    elapsed = update - start
    elapsed_hours = round(elapsed.total_seconds() / 3600, 2)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create tables if they don't exist
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY,
            name TEXT,
            wins TEXT,
            points TEXT,
            ranks TEXT,
            hour TEXT,
            points_pace TEXT,
            wins_pace TEXT,
            points_wins TEXT,
            max_points TEXT,
            max_wins TEXT
        )
    """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS borders (
            rank INTEGER PRIMARY KEY,
            wins TEXT,
            points TEXT,
            hour TEXT,
            points_pace TEXT,
            wins_pace TEXT,
            points_wins TEXT,
            max_points TEXT,
            max_wins TEXT
        )
    """
    )

    tracked_ranks = {1, 5, 10, 20, 30, 50, 75, 100, 1000, 2000, 10000}

    for ranker in data_fetch["players"]:
        player_id = ranker["id"]
        player_name = ranker["name"]
        player_wins = ranker["win_count"]
        player_points = ranker["points"]
        player_rank = ranker["rank"]
        player_points_wins_ratio = (
            int(player_points / player_wins) if player_wins > 0 else 0
        )

        cursor.execute("SELECT * FROM players WHERE id = ?", (player_id,))
        result = cursor.fetchone()

        if result:
            wins = json.loads(result[2])
            points = json.loads(result[3])
            ranks = json.loads(result[4])
            hours = json.loads(result[5])
            points_pace = json.loads(result[6])
            wins_pace = json.loads(result[7])
            points_wins = json.loads(result[8])
            max_points = json.loads(result[9])
            max_wins = json.loads(result[10])

            time_delta = elapsed_hours - hours[-1] if hours else 0

            if time_delta > 0:
                wins.append(player_wins)
                points.append(player_points)
                ranks.append(player_rank)
                hours.append(elapsed_hours)

                if len(hours) <= 5:
                    points_pace.append(
                        int(player_points / elapsed_hours) if elapsed_hours > 0 else 0
                    )
                    wins_pace.append(
                        round(player_wins / elapsed_hours, 2)
                        if elapsed_hours > 0
                        else 0
                    )
                else:
                    time_diff = hours[-1] - hours[-5]
                    points_pace.append(
                        int((points[-1] - points[-5]) / time_diff)
                        if time_diff > 0
                        else 0
                    )
                    wins_pace.append(
                        round((wins[-1] - wins[-5]) / time_diff, 2)
                        if time_diff > 0
                        else 0
                    )

                points_wins.append(player_points_wins_ratio)
                # For manual updates, we don't calculate max projections since tournament might be over
                max_points.append(player_points)
                max_wins.append(player_wins)

                cursor.execute(
                    """
                    UPDATE players SET 
                        name = ?, wins = ?, points = ?, ranks = ?, hour = ?, points_pace = ?, 
                        wins_pace = ?, points_wins = ?, max_points = ?, max_wins = ?
                    WHERE id = ?
                """,
                    (
                        player_name,
                        json.dumps(wins),
                        json.dumps(points),
                        json.dumps(ranks),
                        json.dumps(hours),
                        json.dumps(points_pace),
                        json.dumps(wins_pace),
                        json.dumps(points_wins),
                        json.dumps(max_points),
                        json.dumps(max_wins),
                        player_id,
                    ),
                )
        else:
            points_pace = [
                int(player_points / elapsed_hours) if elapsed_hours > 0 else 0
            ]
            wins_pace = [
                round(player_wins / elapsed_hours, 2) if elapsed_hours > 0 else 0
            ]
            max_points = [player_points]
            max_wins = [player_wins]

            cursor.execute(
                """
                INSERT INTO players (id, name, wins, points, ranks, hour, points_pace, 
                                     wins_pace, points_wins, max_points, max_wins) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    player_id,
                    player_name,
                    json.dumps([player_wins]),
                    json.dumps([player_points]),
                    json.dumps([player_rank]),
                    json.dumps([elapsed_hours]),
                    json.dumps(points_pace),
                    json.dumps(wins_pace),
                    json.dumps([player_points_wins_ratio]),
                    json.dumps(max_points),
                    json.dumps(max_wins),
                ),
            )

        # Handle border tracking
        if player_rank in tracked_ranks:
            cursor.execute("SELECT * FROM borders WHERE rank = ?", (player_rank,))
            border_result = cursor.fetchone()

            if border_result:
                wins = json.loads(border_result[1])
                points = json.loads(border_result[2])
                hours = json.loads(border_result[3])
                points_pace = json.loads(border_result[4])
                wins_pace = json.loads(border_result[5])
                points_wins = json.loads(border_result[6])
                max_points = json.loads(border_result[7])
                max_wins = json.loads(border_result[8])

                time_delta = elapsed_hours - hours[-1] if hours else 0

                if time_delta > 0:
                    wins.append(player_wins)
                    points.append(player_points)
                    hours.append(elapsed_hours)

                    if len(hours) <= 5:
                        points_pace.append(
                            int(player_points / elapsed_hours)
                            if elapsed_hours > 0
                            else 0
                        )
                        wins_pace.append(
                            round(player_wins / elapsed_hours, 2)
                            if elapsed_hours > 0
                            else 0
                        )
                    else:
                        time_diff = hours[-1] - hours[-5]
                        points_pace.append(
                            abs(int((points[-1] - points[-5]) / time_diff))
                            if time_diff > 0
                            else 0
                        )
                        wins_pace.append(
                            abs(round((wins[-1] - wins[-5]) / time_diff, 2))
                            if time_diff > 0
                            else 0
                        )

                    points_wins.append(player_points_wins_ratio)
                    max_points.append(player_points)
                    max_wins.append(player_wins)

                    cursor.execute(
                        """
                        UPDATE borders SET 
                            wins = ?, points = ?, hour = ?, points_pace = ?, 
                            wins_pace = ?, points_wins = ?, max_points = ?, max_wins = ?
                        WHERE rank = ?
                    """,
                        (
                            json.dumps(wins),
                            json.dumps(points),
                            json.dumps(hours),
                            json.dumps(points_pace),
                            json.dumps(wins_pace),
                            json.dumps(points_wins),
                            json.dumps(max_points),
                            json.dumps(max_wins),
                            player_rank,
                        ),
                    )
            else:
                points_pace = [
                    int(player_points / elapsed_hours) if elapsed_hours > 0 else 0
                ]
                wins_pace = [
                    round(player_wins / elapsed_hours, 2) if elapsed_hours > 0 else 0
                ]
                max_points = [player_points]
                max_wins = [player_wins]

                cursor.execute(
                    """
                    INSERT INTO borders (rank, wins, points, hour, points_pace, 
                                         wins_pace, points_wins, max_points, max_wins) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        player_rank,
                        json.dumps([player_wins]),
                        json.dumps([player_points]),
                        json.dumps([elapsed_hours]),
                        json.dumps(points_pace),
                        json.dumps(wins_pace),
                        json.dumps([player_points_wins_ratio]),
                        json.dumps(max_points),
                        json.dumps(max_wins),
                    ),
                )

    conn.commit()
    conn.close()


# This script updates the data using all the fetch files without calling the API
region = "JP"
fetch_dir = f"instances/{region}/fetches"

# Load the correct start timestamp from metadata.json
metadata_path = f"instances/{region}/metadata.json"
start_timestamp = None
is_metadata_start = False

try:
    with open(metadata_path, "r") as f:
        metadata = json.load(f)
    start_timestamp = metadata["start_at"]
    is_metadata_start = True
    print(f"Found tournament start timestamp in metadata: {start_timestamp}")
except (FileNotFoundError, KeyError, json.JSONDecodeError) as e:
    print(f"Warning: Could not load start timestamp from metadata.json: {e}")
    # Fallback to old method
    first_fetch_path, first_fetch_data = find_first_fetch_with_players(fetch_dir)
    if first_fetch_data:
        start_timestamp = first_fetch_data["rank1000_updated_at"]
        is_metadata_start = False
        print(f"Using fallback: Found first fetch with players: {first_fetch_path}")
        print(f"Fallback start timestamp: {start_timestamp}")
    else:
        print("Error: Could not determine tournament start time")

i = 0
while os.path.exists(f"instances/{region}/fetches/fetch{i}.json"):
    with open(f"instances/{region}/fetches/fetch{i}.json", "r") as e:
        data = json.load(e)
    print(f"Updating fetch {i}")
    update_data_manual(
        data,
        f"instances/{region}/database.db",
        region=region,
        start_timestamp=start_timestamp,
        is_metadata_start=is_metadata_start,
    )
    i += 1

print(f"Updated {i} fetch files for region {region}")
