import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta

import requests

from cogs.utils import get_region_config
from config import API_TOKEN
from update_db import update_data


def save_json_to_file(data, filename, fetch_path):
    """Save JSON data to file in the specified fetch path"""
    os.makedirs(fetch_path, exist_ok=True)
    with open(os.path.join(fetch_path, filename), "w") as f:
        json.dump(data, f, indent=4)


def save_metadata(metadata, region):
    """Save metadata to the instances directory"""
    region_cfg = get_region_config(region)
    instances_path = os.path.dirname(
        region_cfg["FETCH_PATH"]
    )  # Remove /fetches from the path
    metadata_path = os.path.join(instances_path, "metadata.json")

    os.makedirs(instances_path, exist_ok=True)
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=4)


def latest_fetch(fetch_path):
    """Find the latest fetch file in the directory"""
    if not os.path.exists(fetch_path):
        return None

    i = 0
    while True:
        filename = f"fetch{i}.json"
        file_path = os.path.join(fetch_path, filename)
        if not os.path.exists(file_path):
            break
        i += 1

    if i == 0:
        return None

    latest_file = os.path.join(fetch_path, f"fetch{i-1}.json")
    return latest_file if os.path.exists(latest_file) else None


def fetch_data(size: int = 1000, region="GLB"):
    """Fetch tournament data from the API"""
    region_cfg = get_region_config(region)
    headers = {"x-apitoken": API_TOKEN, "User-Agent": region_cfg["USER_AGENT"]}
    response = requests.get(
        f"{region_cfg['API_BASE_URL']}/api/budokai/{region_cfg['WT_EDITION']}/players/live?size={size}",
        headers=headers,
    )
    # response.raise_for_status()  # Raise an error for bad status codes
    data = response.json()
    return data


def dynamic_print(last_fetch, updated_time, next_api_call, region):
    """Print dynamic status information"""
    sys.stdout.write(
        f"\r[{region}] Last Fetch: {last_fetch} | Updated At: {datetime.fromtimestamp(updated_time).strftime('%Y-%m-%d %H:%M:%S')} | Next API Call: {next_api_call}"
    )
    sys.stdout.flush()


def main_loop(region="GLB"):
    """Main fetch and save loop"""
    region_cfg = get_region_config(region)
    fetch_path = region_cfg["FETCH_PATH"]
    db_path = region_cfg["DB_PATH"]
    region_tz = region_cfg["TIMEZONE"]

    # Ensure directories exist
    os.makedirs(fetch_path, exist_ok=True)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    # Load or create config.json in the fetch directory
    config_path = os.path.join(fetch_path, "config.json")
    try:
        with open(config_path, "r") as file:
            config = json.load(file)
    except FileNotFoundError:
        config = {"LAST_FETCH": 0, "LAST_UPDATED_AT": 0}
        with open(config_path, "w") as file:
            json.dump(config, file, indent=4)

    # Ensure LAST_UPDATED_AT exists in config
    if "LAST_UPDATED_AT" not in config:
        config["LAST_UPDATED_AT"] = 0

    print(f"Starting fetch loop for {region} region...")
    print(f"Database: {db_path}")
    print(f"Fetch path: {fetch_path}")
    print(f"Timezone: {region_tz}")

    while True:
        try:
            headers = {"User-Agent": region_cfg["USER_AGENT"]}
            ping = requests.get(
                f"{region_cfg['API_BASE_URL']}/api/budokai/{region_cfg['WT_EDITION']}",
                headers=headers,
            )

            # Get current time in region timezone
            current_time = datetime.now(region_tz)
            updated_time = current_time.timestamp()

            if ping.status_code != 404:
                cond = (
                    ping.json()
                )  # Just a "ping" to get the latest rank1000_updated_at

                # Save metadata
                save_metadata(cond, region)

                # Check if data has been updated since last fetch
                current_updated_at = cond["rank1000_updated_at"]

                if current_updated_at != config["LAST_UPDATED_AT"]:
                    print(f"\n[{region}] New data detected! Fetching...")

                    # Check if top10k is also updated
                    if cond["rank1000_updated_at"] == cond["rank10000_updated_at"]:
                        fetch = fetch_data(size=10000, region=region)
                        print(f"[{region}] Fetched top 10,000 players")
                    else:
                        fetch = fetch_data(size=1000, region=region)
                        print(f"[{region}] Fetched top 1,000 players")

                    save_json_to_file(
                        fetch, f"fetch{config['LAST_FETCH']}.json", fetch_path
                    )
                    updated_time = cond["rank1000_updated_at"]
                    config["LAST_FETCH"] += 1
                    config["LAST_UPDATED_AT"] = current_updated_at

                    with open(config_path, "w") as file:
                        json.dump(config, file, indent=4)

                    try:
                        print(f"[{region}] Updating database...")
                        update_data(fetch, db_path, region)
                        print(f"[{region}] Database updated successfully!")
                    except Exception as e:
                        print(f"[{region}] Database update error: {e}")

                    # Display dynamic output
                    next_api_call = (current_time + timedelta(minutes=3)).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                    dynamic_print(
                        config["LAST_FETCH"] - 1, updated_time, next_api_call, region
                    )
                else:
                    print(
                        f"\r[{region}] No new data (last update: {datetime.fromtimestamp(current_updated_at).strftime('%Y-%m-%d %H:%M:%S')})",
                        end="",
                    )
                    sys.stdout.flush()

            else:
                print(f"\n[{region}] API not available (404)")

        except Exception as e:
            print(f"\n[{region}] Error in main loop: {e}")

        time.sleep(3 * 60)  # Wait 3 minutes


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fetch and save tournament data with region support"
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

    print(f"Starting fetch_and_save for region: {region}")

    try:
        main_loop(region)
    except KeyboardInterrupt:
        print(f"\nStopped fetch_and_save for region: {region}")
    except Exception as e:
        print(f"\nFatal error in fetch_and_save for region {region}: {e}")
