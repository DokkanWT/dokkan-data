import json
import os
import sqlite3
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify, request

from config import USER_AGENT, WT_EDITION

app = Flask(__name__)
DB_PATH = "database.db"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def get_random_user():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM players ORDER BY RANDOM() LIMIT 1")
    user = cursor.fetchone()
    conn.close()
    return user


def latest_fetch():
    output_dir = os.path.join(BASE_DIR, "./fetches")
    i = 0
    while True:
        filename = f"fetch{i}.json"
        if not os.path.exists(os.path.join(output_dir, filename)):
            break
        i += 1
    latest_file = os.path.join(output_dir, f"fetch{i-1}.json")
    return latest_file if os.path.exists(latest_file) else None


def time_data():
    latest_fetch_path = latest_fetch()

    if latest_fetch_path:
        with open(latest_fetch_path, "r") as file:
            data = json.load(file)
            headers = {"User-Agent": USER_AGENT}
            ping = requests.get(
                f"https://dokkan.wiki/api/budokai/{WT_EDITION}", headers=headers
            )
            ping.raise_for_status()
            start_end = ping.json()
            start = datetime.utcfromtimestamp(start_end["start_at"]).replace(
                tzinfo=timezone.utc
            )
            end = datetime.utcfromtimestamp(start_end["end_at"]).replace(
                tzinfo=timezone.utc
            )
            update = datetime.utcfromtimestamp(data["rank1000_updated_at"]).replace(
                tzinfo=timezone.utc
            )
            total = end - start
            left = end - update
            elapsed = update - start
            return update, start, end, total, left, elapsed
    else:
        return None, None, None, None, None, None


def get_top100_users():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    update, start, end, total, left, elapsed = time_data()
    latest_hour = round(elapsed.days * 24 + elapsed.seconds / 3600, 2)
    conn.create_function("strrev", 1, lambda s: s[::-1])
    cursor.execute(
        """
        SELECT id, CAST (SUBSTR(ranks, LENGTH(ranks) - INSTR(strrev(ranks), ',') + 2, LENGTH(ranks)) AS INTEGER) AS latest_rank FROM players
        WHERE CAST(SUBSTR(hour, LENGTH(hour) - INSTR(strrev(hour), ',') + 2, LENGTH(hour)) AS FLOAT) = ?
        ORDER BY latest_rank ASC
        LIMIT 100
    """,
        (latest_hour,),
    )
    data = cursor.fetchall()
    users_id = [row[0] for row in data]
    users = []
    for i in users_id:
        user, multiple = get_user_by_identifier(i)
        if multiple:
            return
        users.append(user)
    return users


def get_user_by_identifier(identifier):
    multiple_users = False
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM players WHERE id = ?", (identifier,))
    user = cursor.fetchone()

    if not user:
        count = cursor.execute(
            "SELECT COUNT(*) FROM players WHERE name = ?", (identifier,)
        ).fetchone()[0]

        cursor.execute("SELECT * FROM players WHERE name = ?", (identifier,))
        if count > 1:
            multiple_users = True
            user = cursor.fetchall()
        else:
            user = cursor.fetchone()

    conn.close()
    return user, multiple_users


@app.route("/api/get-user", methods=["GET"])
def get_user():
    random_flag = request.args.get("random", "false").lower() == "true"
    identifier = request.args.get("identifier")

    if random_flag:
        user = get_random_user()
        if not user:
            return jsonify({"error": "No users found in the database."}), 404
        user_data = format_user_data(user)
    else:
        if not identifier:
            return (
                jsonify({"error": "Identifier is required when 'random' is not true."}),
                400,
            )

        users, multiple_users = get_user_by_identifier(identifier)

        if multiple_users:
            if not users:
                return (
                    jsonify({"error": f"No users found with name '{identifier}'."}),
                    404,
                )

            user_data = [format_user_data(user) for user in users]
        else:
            if not users:
                return (
                    jsonify(
                        {"error": f"No user found with identifier '{identifier}'."}
                    ),
                    404,
                )

            user_data = format_user_data(users)

    return jsonify(user_data)


@app.route("/api/get-top100", methods=["GET"])
def get_top100():
    users = get_top100_users()
    user_data = [format_user_data(user) for user in users]
    if not user_data:
        return jsonify({"error": "No users found in the top100"}), 404
    return jsonify(user_data)


def format_user_data(user):
    return {
        "id": user[0],
        "name": user[1],
        "wins": user[2],
        "points": user[3],
        "ranks": user[4],
        "hour": user[5],
        "points_pace": user[6],
        "wins_pace": user[7],
        "points_wins": user[8],
        "max_points": user[9],
        "max_wins": user[10],
    }


if __name__ == "__main__":
    app.run(host="0.0.0.0", port="2176")
