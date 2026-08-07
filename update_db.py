import argparse
import json
import os
import random
import sqlite3
from datetime import datetime, timedelta, timezone

import requests

from cogs.utils import get_region_config, time_data


def update_json_data_to_db(json_path, db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

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
    with open(json_path, "r") as file:
        json_data = json.load(file)
    i = 0
    for player in json_data:
        cursor.execute("SELECT * FROM players WHERE id = ?", (player["id"],))
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

            wins.append(player["wins"])
            points.append(player["points"])
            ranks.append(player["ranks"])
            hours.append(player["hour"])
            points_pace.append(player["points_pace"])
            wins_pace.append(player["wins_pace"])
            points_wins.append(player["points_wins"])
            max_points.append(player["max_points"])
            max_wins.append(player["max_wins"])

            cursor.execute(
                """
                UPDATE players SET 
                    wins = ?, points = ?, ranks = ?, hour = ?, points_pace = ?, 
                    wins_pace = ?, points_wins = ?, max_points = ?, max_wins = ?
                WHERE id = ?
            """,
                (
                    json.dumps(wins),
                    json.dumps(points),
                    json.dumps(ranks),
                    json.dumps(hours),
                    json.dumps(points_pace),
                    json.dumps(wins_pace),
                    json.dumps(points_wins),
                    json.dumps(max_points),
                    json.dumps(max_wins),
                    player["id"],
                ),
            )
            i += 1
        else:
            # No player has been found so we need to insert it into the db
            cursor.execute(
                """
                INSERT INTO players (id, name, wins, points, ranks, hour, points_pace, 
                                     wins_pace, points_wins, max_points, max_wins) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    player["id"],
                    player["name"],
                    json.dumps(player["wins"]),
                    json.dumps(player["points"]),
                    json.dumps(player["ranks"]),
                    json.dumps(player["hour"]),
                    json.dumps(player["points_pace"]),
                    json.dumps(player["wins_pace"]),
                    json.dumps(player["points_wins"]),
                    json.dumps(player["max_points"]),
                    json.dumps(player["max_wins"]),
                ),
            )
            i += 1
        # print(f"[{i}] Player {player['name']} updated")
    conn.commit()
    conn.close()


def update_data(data_fetch, db_path, region="GLB", update_ping=True):
    update = datetime.utcfromtimestamp(data_fetch["rank1000_updated_at"]).replace(
        tzinfo=timezone.utc
    )
    region_cfg = get_region_config(region)
    headers = {"User-Agent": region_cfg["USER_AGENT"]}
    ping = requests.get(
        f"{region_cfg['API_BASE_URL']}/api/budokai/{region_cfg['WT_EDITION']}",
        headers=headers,
    )
    ping.raise_for_status()
    start_end = ping.json()
    start = datetime.utcfromtimestamp(start_end["start_at"]).replace(
        tzinfo=timezone.utc
    )
    end = datetime.utcfromtimestamp(start_end["end_at"]).replace(tzinfo=timezone.utc)

    total = end - start
    left = end - update
    elapsed = update - start
    elapsed_hours = round(elapsed.total_seconds() / 3600, 2)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
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
                    points_pace.append(int(player_points / elapsed_hours))
                    wins_pace.append(round(player_wins / elapsed_hours, 2))
                else:
                    points_pace.append(
                        int((points[-1] - points[-5]) / (hours[-1] - hours[-5]))
                    )
                    wins_pace.append(
                        round((wins[-1] - wins[-5]) / (hours[-1] - hours[-5]), 2)
                    )

                points_wins.append(player_points_wins_ratio)
                max_points.append(
                    int(
                        player_points + max(points_pace) * (left.total_seconds() / 3600)
                    )
                )
                max_wins.append(
                    int(player_wins + max(wins_pace) * (left.total_seconds() / 3600))
                )

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
            points_pace = [int(player_points / elapsed_hours)]
            wins_pace = [round(player_wins / elapsed_hours, 2)]
            max_points = [
                int(player_points + points_pace[0] * (left.total_seconds() / 3600))
            ]
            max_wins = [int(player_wins + wins_pace[0] * (left.total_seconds() / 3600))]

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
                        points_pace.append(int(player_points / elapsed_hours))
                        wins_pace.append(round(player_wins / elapsed_hours, 2))
                    else:
                        points_pace.append(
                            abs(
                                int((points[-1] - points[-5]) / (hours[-1] - hours[-5]))
                            )
                        )
                        wins_pace.append(
                            abs(
                                round(
                                    (wins[-1] - wins[-5]) / (hours[-1] - hours[-5]), 2
                                )
                            )
                        )

                    points_wins.append(player_points_wins_ratio)
                    max_points.append(
                        int(
                            player_points
                            + max(points_pace) * (left.total_seconds() / 3600)
                        )
                    )
                    max_wins.append(
                        int(
                            player_wins + max(wins_pace) * (left.total_seconds() / 3600)
                        )
                    )

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
                cursor.execute(
                    """
                    INSERT INTO borders (rank, wins, points, hour, points_pace, wins_pace, 
                                         points_wins, max_points, max_wins) 
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
    if update_ping:
        # Send Flask notification using region-specific UPDATE_TOKEN
        FLASK_UPDATE_URL = "http://127.0.0.1:2176/notify_update"
        headers = {"Authorization": f"Bearer {region_cfg['UPDATE_TOKEN']}"}
        try:
            response = requests.post(FLASK_UPDATE_URL, headers=headers)
            if response.status_code == 200:
                print("Update notification sent successfully!")
            else:
                print(f"Failed to send update. Status code: {response.status_code}")
                print(response.text)
        except Exception as e:
            print(f"Error sending update: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Update database with region-specific data"
    )
    parser.add_argument(
        "--GLB",
        action="store_const",
        const="GLB",
        dest="region",
        help="Use GLB region (default)",
    )
    parser.add_argument(
        "--JP", action="store_const", const="JP", dest="region", help="Use JP region"
    )
    parser.set_defaults(region="GLB")

    args = parser.parse_args()
    region = args.region

    print(f"Running update_db for region: {region}")

    # Get region-specific configuration
    region_cfg = get_region_config(region)

    # This script is typically called by fetch_and_save.py, so we don't run anything here
    # The functions are available to be imported and used
