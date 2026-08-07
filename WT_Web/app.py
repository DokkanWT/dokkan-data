import glob
import json
import os
import queue
import requests
import shutil
import sqlite3
import sys
import threading
import time
from datetime import datetime, timezone, timedelta

# Set environment variable for web rendering BEFORE other imports
os.environ["WT_WEB_RENDER"] = "1"

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from cogs.utils import get_region_config, load_db_data, time_data
from config import BOTS
from flask import (Flask, Response, jsonify, make_response, redirect,
                   render_template, request, send_from_directory,
                   stream_with_context, url_for)
from functools import wraps

from chartjs_render import get_chart_data

app = Flask(__name__)


# ================== CORS Decorator for API Routes ==================
def add_cors_headers(f):
    """Decorator to add CORS headers to API routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        response = f(*args, **kwargs)
        if isinstance(response, tuple):
            # If response is a tuple (response, status_code), convert to Response object
            response_obj = make_response(response[0], response[1])
        elif hasattr(response, 'headers'):
            # If it's already a Response object
            response_obj = response
        else:
            # If it's just data, convert to Response
            response_obj = make_response(response)
        
        response_obj.headers['Access-Control-Allow-Origin'] = '*'
        return response_obj
    return decorated_function


# ================== Region Detection ==================
@app.before_request
def detect_region():
    host = request.host.lower()
    if host.startswith("jpn.") or request.args.get("region") == "JP":
        request.region = "JP"
    else:
        request.region = "GLB"


# ================== SSE & Update Notification Setup ==================

clients = []


@app.route("/events")
def sse_events():
    def event_stream():
        q = []
        clients.append(q)
        try:
            while True:
                if q:
                    msg = q.pop(0)
                    yield f"data: {msg}\n\n"
                else:
                    # Keep connection alive with a comment every 15 seconds
                    yield ": keep-alive\n\n"
                    time.sleep(1)
        except GeneratorExit:
            clients.remove(q)

    return Response(event_stream(), mimetype="text/event-stream")


@app.route("/notify_update", methods=["POST"])
def notify_update():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    region = getattr(request, "region", "GLB")
    region_cfg = get_region_config(region)
    if token != region_cfg["UPDATE_TOKEN"]:
        return "Unauthorized", 401

    # Send update to all clients
    for q in clients:
        q.append("update")
    return "Update sent", 200


# ================== Utility Functions ==================


def get_top100_users(region=None):
    if region is None:
        region = getattr(request, "region", "GLB")
    conn = load_db_data(region)
    cursor = conn.cursor()
    update, start, end, total, left, elapsed = time_data(region=region)
    latest_hour = round(elapsed.days * 24 + elapsed.seconds / 3600, 2)

    conn.create_function("strrev", 1, lambda s: None if s is None else str(s)[::-1])

    cursor.execute(
        """
        SELECT id, 
               CAST(
                   SUBSTR(
                       CAST(ranks AS TEXT), 
                       LENGTH(CAST(ranks AS TEXT)) - INSTR(strrev(CAST(ranks AS TEXT)), ',') + 2, 
                       LENGTH(CAST(ranks AS TEXT))
                   ) AS INTEGER
               ) AS latest_rank
        FROM players
        WHERE CAST(
                  SUBSTR(
                      CAST(hour AS TEXT), 
                      LENGTH(CAST(hour AS TEXT)) - INSTR(strrev(CAST(hour AS TEXT)), ',') + 2, 
                      LENGTH(CAST(hour AS TEXT))
                  ) AS FLOAT
              ) = ?
        ORDER BY latest_rank ASC
        LIMIT 100
        """,
        (latest_hour,),
    )

    data = cursor.fetchall()
    users_id = [row[0] for row in data]

    users = []
    for i in users_id:
        user, multiple = get_user_by_identifier(i, region)
        if multiple:
            return
        users.append(user)

    conn.close()
    return users


def get_user_by_identifier(identifier, region=None):
    multiple_users = False
    if region is None:
        region = getattr(request, "region", "GLB")
    region_cfg = get_region_config(region)
    DB_PATH = region_cfg["DB_PATH"]
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
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


def get_available_editions():
    # Wait actually instead of asking which region it is we can just get every edition in both regions and display them all
    regions = ["GLB", "JP"]
    editions = {}
    
    for region in regions:
        editions[region] = []
        editions_dir = os.path.join(
            os.path.dirname(__file__), "..", "older_editions", region
        )
        if not os.path.exists(editions_dir):
            continue
        for edition in os.listdir(editions_dir):
            edition_path = os.path.join(editions_dir, edition)
            if not os.path.isdir(edition_path):
                continue
            edition_db_path = os.path.join(edition_path, f"{edition}.db")
            if not os.path.exists(edition_db_path):
                continue

            conn = sqlite3.connect(f"file:{edition_db_path}?mode=ro", uri=True)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM players")
            player_count = cursor.fetchone()[0]
            conn.close()

            edition_dir = edition
            name = edition_dir
            editions[region].append(
                {
                    "filename": f"{edition_dir}.db",
                    "name": f"{name}th World Tournament",
                    "description": f"Historical data from the {name}th World Tournament",
                    "player_count": player_count,
                    "edition_number": (
                        int(edition_dir) if edition_dir.isdigit() else 0
                    ),
                }
            )
            
    # Sort editions by edition_number descending
    for region in editions:
        editions[region].sort(key=lambda x: x["edition_number"], reverse=True)

    return editions


def load_db_data_with_database(database=None, region="GLB"):
    if region not in ["GLB", "JP"]:
        region = "GLB"
    if database and database != "None":
        edition_name = database.replace(".db", "")
        db_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "older_editions",
            region,
            edition_name,
            f"{edition_name}.db",
        )
        if not os.path.exists(db_path):
            return None
        return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    else:
        try:
            return load_db_data(region)
        except Exception:
            # Current database doesn't exist (no active tournament)
            return None


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


def process_gap_data(player, pro, noob, update):
    gap_data = {"player": player, "pro": None, "noob": None, "update_str": None}

    if update and hasattr(update, "strftime"):
        if update.tzinfo:
            gap_data["update_str"] = update.strftime("%Y-%m-%d %H:%M:%S %Z")
        else:
            gap_data["update_str"] = update.strftime("%Y-%m-%d %H:%M:%S UTC")
    elif update:
        gap_data["update_str"] = str(update)

    if pro:
        pro_gap = abs(pro["points"][-1] - player["points"][-1])
        delta_pro = (
            pro_gap - abs(pro["points"][-2] - player["points"][-2])
            if len(player["points"]) >= 2 and len(pro["points"]) >= 2
            else 0
        )
        estimated_time_pro = (
            int(pro_gap / (abs(delta_pro) * 4 / 60)) if delta_pro != 0 else 0
        )
        gap_data["pro"] = {
            "name": pro["name"],
            "rank": pro["ranks"][-1],
            "points": pro["points"][-1],
            "gap": pro_gap,
            "delta": delta_pro,
            "estimated_time": estimated_time_pro,
            "is_faster": delta_pro > 0,
        }

    if noob:
        noob_gap = abs(noob["points"][-1] - player["points"][-1])
        delta_noob = (
            noob_gap - abs(noob["points"][-2] - player["points"][-2])
            if len(player["points"]) >= 2 and len(noob["points"]) >= 2
            else 0
        )
        gap_data["noob"] = {
            "name": noob["name"],
            "rank": noob["ranks"][-1],
            "points": noob["points"][-1],
            "gap": noob_gap,
            "delta": delta_noob,
        }

    return gap_data


def get_random_user():
    region = getattr(request, "region", "GLB")
    conn = load_db_data(region)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM players ORDER BY RANDOM() LIMIT 1")
    user = cursor.fetchone()
    conn.close()
    return user


@app.route("/", methods=["GET"])
def leaderboard():
    # Get region from request context
    region = getattr(request, "region", "GLB")
    
    # Get leaderboard type from query parameter, default to 'points'
    leaderboard_types = [
        "wins_pace",
        "points_pace",
        "wins",
        "points",
        "points_wins",
        "ranks",
    ]
    type = request.args.get("type", "points")
    if type not in leaderboard_types:
        type = "points"
    
    region_cfg = get_region_config(region)
    db_path = region_cfg["DB_PATH"]
    if not os.path.exists(db_path):
        return render_template(
            "leaderboard.html",
            players=[],
            page=1,
            type=type,
            leaderboard_types=leaderboard_types,
            no_tournament=True,
            region=region,
        )

    conn = load_db_data(region)
    update, start, end, total, left, elapsed = time_data(region=region)
    datatypes = {
        "wins_pace": "FLOAT",
        "points_pace": "FLOAT",
        "wins": "INTEGER",
        "points": "INTEGER",
        "points_wins": "FLOAT",
        "ranks": "INTEGER",
    }
    players_per_page = 10
    page = int(request.args.get("page", 1))
    offset = (page - 1) * players_per_page
    calculated_hour = (
        round(elapsed.days * 24 + elapsed.seconds / 3600, 2)
        if elapsed is not None
        else None
    )
    current_hour = (
        71.26 if calculated_hour is None or calculated_hour < 0 else calculated_hour
    )
    print(f"  current_hour: {current_hour}")
    conn.create_function("strrev", 1, lambda s: s[::-1])
    # Use ASC for ranks (lower is better), DESC for everything else
    order_clause = "ASC" if type == "ranks" else "DESC"
    query = f"""
        SELECT id, name,
               CAST(SUBSTR({type}, LENGTH({type}) - INSTR(strrev({type}), ',') + 2, LENGTH({type})) AS {datatypes[type]}) AS latest_type_value
        FROM players
        WHERE CAST(SUBSTR(hour, LENGTH(hour) - INSTR(strrev(hour), ',') + 2, LENGTH(hour)) AS FLOAT) > 0
        ORDER BY latest_type_value {order_clause}
        LIMIT ? OFFSET ?
    """
    cursor = conn.cursor()
    cursor.execute(query, (players_per_page, offset))
    players = cursor.fetchall()
    conn.close()
    return render_template(
        "leaderboard.html",
        players=players,
        page=page,
        type=type,
        leaderboard_types=leaderboard_types,
        region=region,
    )


def find_rank_for_edition(conn, rank, edition, region):
    """Find player ID by rank for a specific edition"""
    cursor = conn.cursor()
    
    if edition == 0:
        # For current tournament, use time_data to get current elapsed hours
        from cogs.utils import time_data
        update, start, end, total, left, elapsed = time_data(region=region)
        if elapsed:
            elapsed_hours = round(elapsed.total_seconds() / 3600, 2)
        else:
            return None
    else:
        # For historical editions, find the latest hour in the database
        conn.create_function("strrev", 1, lambda s: None if s is None else str(s)[::-1])
        cursor.execute("SELECT MAX(CAST(SUBSTR(hour, LENGTH(hour) - INSTR(strrev(hour), ',') + 2, LENGTH(hour)) AS FLOAT)) FROM players")
        max_hour_result = cursor.fetchone()
        elapsed_hours = max_hour_result[0] if max_hour_result and max_hour_result[0] else 0
    
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
    return row[0] if row else None

def get_user_for_edition(edition, region):
    """Get user data for a specific edition or current tournament (edition 0)"""
    random_flag = request.args.get("random", "false").lower() == "true"
    identifier = request.args.get("identifier")
    rank = request.args.get("rank")

    # Ongoing = 0 
    if edition == 0:
        region_cfg = get_region_config(region)
        db_path = region_cfg["DB_PATH"]
        if not os.path.exists(db_path):
            return jsonify({"error": "No ongoing World Tournament", "message": f"There is currently no active World Tournament in the {region} region."}), 404
        
        database = None
    else:
        database = f"{edition}.db"
    
    try:
        if random_flag:
            if edition == 0:
                user = get_random_user()
            else:
                conn = load_db_data_with_database(database, region)
                if not conn:
                    return jsonify({"error": "Edition not found", "message": f"Edition {edition} not found for {region} region."}), 404
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM players ORDER BY RANDOM() LIMIT 1")
                user = cursor.fetchone()
                conn.close()
                
            if not user:
                return jsonify({"error": "No users found in the database."}), 404
            user_data = format_user_data(user)
        
        elif rank:
            try:
                rank_number = int(rank)
                if rank_number < 1:
                    return jsonify({"error": "Rank must be a positive integer."}), 400
            except ValueError:
                return jsonify({"error": "Rank must be a valid integer."}), 400
            
            if edition == 0:
                conn = load_db_data(region)
                if not conn:
                    return jsonify({"error": "No ongoing World Tournament", "message": f"There is currently no active World Tournament in the {region} region."}), 404
            else:
                conn = load_db_data_with_database(database, region)
                if not conn:
                    return jsonify({"error": "Edition not found", "message": f"Edition {edition} not found for {region} region."}), 404
            
            player_id = find_rank_for_edition(conn, rank_number, edition, region)
            if not player_id:
                conn.close()
                return jsonify({"error": f"No player found at rank {rank_number}."}), 404
            
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM players WHERE id = ?", (player_id,))
            user = cursor.fetchone()
            conn.close()
            
            if not user:
                return jsonify({"error": f"No player found at rank {rank_number}."}), 404
            
            user_data = format_user_data(user)
        
        else:
            if not identifier:
                return jsonify({"error": "Either 'identifier' or 'rank' parameter is required when 'random' is not true."}), 400
            
            if edition == 0:
                users, multiple_users = get_user_by_identifier(identifier, region)
            else:
                conn = load_db_data_with_database(database, region)
                if not conn:
                    return jsonify({"error": "Edition not found", "message": f"Edition {edition} not found for {region} region."}), 404
                
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM players WHERE id = ?", (identifier,))
                user = cursor.fetchone()
                multiple_users = False
                
                if not user:
                    count = cursor.execute("SELECT COUNT(*) FROM players WHERE name = ?", (identifier,)).fetchone()[0]
                    cursor.execute("SELECT * FROM players WHERE name = ?", (identifier,))
                    if count > 1:
                        multiple_users = True
                        users = cursor.fetchall()
                    else:
                        users = cursor.fetchone()
                else:
                    users = user
                
                conn.close()

            if multiple_users:
                if not users:
                    return jsonify({"error": f"No users found with name '{identifier}'."}), 404
                user_data = [format_user_data(user) for user in users]
            else:
                if not users:
                    return jsonify({"error": f"No user found with identifier '{identifier}'."}), 404
                user_data = format_user_data(users)

        return jsonify(user_data)
    except Exception as e:
        if edition == 0:
            return jsonify({"error": "No ongoing World Tournament", "message": f"There is currently no active World Tournament in the {region} region."}), 404
        else:
            return jsonify({"error": "Edition not found", "message": f"Edition {edition} not found for {region} region."}), 404

@app.route("/api/<int:edition>/get-user", methods=["GET"])
@add_cors_headers
def get_user_edition(edition):
    region = getattr(request, "region", "GLB")
    
    return get_user_for_edition(edition, region)

@app.route("/api/get-user", methods=["GET"])
@add_cors_headers
def get_user():
    region = getattr(request, "region", "GLB")
    if request.args.get("region"):
        region = request.args.get("region")
    
    return get_user_for_edition(0, region)


def get_top100_for_edition(edition, region):
    """Get top 100 users for a specific edition or current tournament (edition 0)"""
    try:
        # 0 = ongoing
        if edition == 0:
            region_cfg = get_region_config(region)
            db_path = region_cfg["DB_PATH"]
            if not os.path.exists(db_path):
                return jsonify({"error": "No ongoing World Tournament", "message": f"There is currently no active World Tournament in the {region} region."}), 404
            
            users = get_top100_users(region)
        else:
            database = f"{edition}.db"
            conn = load_db_data_with_database(database, region)
            if not conn:
                return jsonify({"error": "Edition not found", "message": f"Edition {edition} not found for {region} region."}), 404
            
            cursor = conn.cursor()
            conn.create_function("strrev", 1, lambda s: None if s is None else str(s)[::-1])
            
            cursor.execute("SELECT MAX(CAST(SUBSTR(hour, LENGTH(hour) - INSTR(strrev(hour), ',') + 2, LENGTH(hour)) AS FLOAT)) FROM players")
            max_hour_result = cursor.fetchone()
            latest_hour = max_hour_result[0] if max_hour_result and max_hour_result[0] else 0
            
            cursor.execute(
                """
                SELECT id, 
                       CAST(
                           SUBSTR(
                               CAST(ranks AS TEXT), 
                               LENGTH(CAST(ranks AS TEXT)) - INSTR(strrev(CAST(ranks AS TEXT)), ',') + 2, 
                               LENGTH(CAST(ranks AS TEXT))
                           ) AS INTEGER
                       ) AS latest_rank
                FROM players
                WHERE CAST(
                          SUBSTR(
                              CAST(hour AS TEXT), 
                              LENGTH(CAST(hour AS TEXT)) - INSTR(strrev(CAST(hour AS TEXT)), ',') + 2, 
                              LENGTH(CAST(hour AS TEXT))
                          ) AS FLOAT
                      ) = ?
                ORDER BY latest_rank ASC
                LIMIT 100
                """,
                (latest_hour,),
            )
            
            data = cursor.fetchall()
            users_id = [row[0] for row in data]
            
            users = []
            for user_id in users_id:
                cursor.execute("SELECT * FROM players WHERE id = ?", (user_id,))
                user = cursor.fetchone()
                if user:
                    users.append(user)
            
            conn.close()
        
        user_data = [format_user_data(user) for user in users]
        if not user_data:
            return jsonify({"error": "No users found in the top100"}), 404
        return jsonify(user_data)
    
    except Exception as e:
        if edition == 0:
            return jsonify({"error": "No ongoing World Tournament", "message": f"There is currently no active World Tournament in the {region} region."}), 404
        else:
            return jsonify({"error": "Edition not found", "message": f"Edition {edition} not found for {region} region."}), 404

@app.route("/api/<int:edition>/get-top100", methods=["GET"])
@add_cors_headers
def get_top100_edition(edition):
    region = getattr(request, "region", "GLB")
    if request.args.get("region"):
        region = request.args.get("region")
    
    return get_top100_for_edition(edition, region)

@app.route("/api/get-top100", methods=["GET"])
@add_cors_headers
def get_top100():
    region = getattr(request, "region", "GLB")
    if request.args.get("region"):
        region = request.args.get("region")
    
    return get_top100_for_edition(0, region)


def get_metadata_for_edition(edition, region):
    """Get metadata for a specific edition or current tournament (edition 0)"""
    try:
        if edition == 0:
            # Get current edition from config
            region_cfg = get_region_config(region)
            current_edition = region_cfg["WT_EDITION"]
            
            # Check if metadata.json exists for current tournament
            instances_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "instances", region)
            metadata_path = os.path.join(instances_path, "metadata.json")
            
            if os.path.exists(metadata_path):
                with open(metadata_path, "r") as f:
                    metadata = json.load(f)
                return jsonify(metadata)
            else:
                return jsonify({"error": "No ongoing World Tournament", "message": f"No metadata found for current tournament in {region} region."}), 404
        
        else:
            # Historical edition - read metadata.json from older_editions
            metadata_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), 
                "..", 
                "older_editions", 
                region.upper(), 
                str(edition), 
                "metadata.json"
            )
            
            if os.path.exists(metadata_path):
                with open(metadata_path, "r") as f:
                    metadata = json.load(f)
                return jsonify(metadata)
            else:
                return jsonify({"error": "Edition not found", "message": f"Metadata for edition {edition} not found for {region} region."}), 404
    
    except Exception as e:
        return jsonify({"error": "Internal server error", "message": str(e)}), 500

@app.route("/api/<int:edition>/metadata", methods=["GET"])
@add_cors_headers
def get_metadata_edition(edition):
    region = getattr(request, "region", "GLB")
    # Also check for region in query parameters as fallback
    if request.args.get("region"):
        region = request.args.get("region")
    
    return get_metadata_for_edition(edition, region)


@app.route("/player")
def player_detail():
    """Player detail page"""
    region = getattr(request, "region", "GLB")
    if request.args.get("region"):
        region = request.args.get("region")
    
    main_id = request.args.get("main_id")
    compare_ids = request.args.getlist("id")
    stat_type = request.args.get("type", "wins_pace")
    database = request.args.get("database")
    
    if not main_id:
        return redirect(url_for("leaderboard"))

    add_player_id = request.args.get("add_player_id")
    if add_player_id and add_player_id != main_id and add_player_id not in compare_ids:
        compare_ids.append(add_player_id)

    conn = load_db_data_with_database(database, region)
    if not conn:
        if database:
            return f"Database {database} not found for {region} region", 404
        else:
            # No current tournament running
            return render_template(
                "error.html",
                error_title="No Active Tournament",
                error_message=f"There is currently no active World Tournament in the {region} region.",
                back_url=url_for('older_editions')
            )

    from cogs.utils import find_gap, find_player

    player = find_player(conn, main_id)
    if not player:
        conn.close()
        return "Player not found", 404

    if isinstance(player, list):
        player = player[0]

    # Get nearby players for gap analysis (for display purposes)
    pro, noob = find_gap(player, conn)

    # Get comparison players
    players = [player]
    manually_added_players = []

    for compare_id in compare_ids:
        if compare_id != main_id:
            compare_player = find_player(conn, compare_id)
            if compare_player and isinstance(compare_player, dict):
                players.append(compare_player)
                manually_added_players.append(compare_player)

    # Process gap data for template
    # For older editions, pass the edition directory to time_data
    edition_dir = database.replace(".db", "") if database else None
    update, start, end, total, left, elapsed = time_data(
        edition_dir=edition_dir, region=region
    )
    gap_data = process_gap_data(player, pro, noob, update)

    conn.close()

    return render_template(
        "player_detail.html",
        player=player,
        stat_type=stat_type,
        stat_types=[
            "wins_pace",
            "points_pace",
            "wins",
            "points",
            "points_wins",
            "ranks",
        ],
        gap_data=gap_data,
        players=players,
        manually_added_players=manually_added_players,
        current_edition=database,
        region=region,
    )


@app.route("/search_player")
def search_player():
    region = getattr(request, "region", "GLB")
    query = request.args.get("q", "").strip()
    database = request.args.get("database")  # For older editions
    
    if not query:
        return jsonify([])

    # Use database-aware function
    conn = load_db_data_with_database(database, region)
    if not conn:
        return jsonify([])

    from cogs.utils import find_player

    # Try to find by ID or name
    results = []
    if query.isdigit():
        player = find_player(conn, query)
        if player:
            if isinstance(player, list):
                results.extend(player)
            else:
                results.append(player)
    else:
        player = find_player(conn, query)
        if player:
            if isinstance(player, list):
                results.extend(player)
            else:
                results.append(player)
    conn.close()
    # Return up to 10 results as {id, name, rank}
    unique = {}
    for p in results:
        # Get the latest rank if available
        rank = None
        if "ranks" in p and p["ranks"]:
            try:
                rank = int(p["ranks"][-1])
            except Exception:
                rank = None
        if p["id"] not in unique:
            unique[p["id"]] = {"name": p["name"], "rank": rank}
    return jsonify(
        [
            {"id": pid, "name": unique[pid]["name"], "rank": unique[pid]["rank"]}
            for pid in list(unique.keys())[:10]
        ]
    )


@app.route("/chart_data")
def chart_data():
    """Serve chart data as JSON for Chart.js"""
    region = getattr(request, "region", "GLB")
    stat_type = request.args.get("type", "wins_pace")
    player_ids = request.args.getlist("id")
    database = request.args.get("database")  # For older editions
    
    if not player_ids:
        return jsonify({"error": "No player IDs provided"})

    # Use the first player as main, others as comparison
    main_player_id = player_ids[0]
    compare_ids = player_ids[1:] if len(player_ids) > 1 else []

    chart_config = get_chart_data(
        main_player_id, stat_type, compare_ids, database=database, region=region
    )
    return jsonify(chart_config)


@app.route("/chart_data_personal")
def chart_data_personal():
    """Serve chart data for personal performance page"""
    region = getattr(request, "region", "GLB")
    player_id = request.cookies.get("player_id")
    if not player_id:
        return jsonify({"error": "No player ID in cookies"})

    stat_type = request.args.get("type", "wins_pace")
    compare_ids = request.args.getlist("id")
    include_nearby = request.args.get("include_nearby") == "true"

    chart_config = get_chart_data(player_id, stat_type, compare_ids, include_nearby, region=region)
    return jsonify(chart_config)


def process_gap_data(player, pro, noob, update):
    """Process gap data for template display"""
    gap_data = {
        "player": player,
        "pro": None,
        "noob": None,
        "update_str": None,  # Changed from 'update' to 'update_str' to avoid method conflict
    }

    # Convert update to string if it's a datetime object
    if update and hasattr(update, "strftime"):
        # Check if it has timezone info
        if update.tzinfo:
            gap_data["update_str"] = update.strftime("%Y-%m-%d %H:%M:%S %Z")
        else:
            gap_data["update_str"] = update.strftime("%Y-%m-%d %H:%M:%S UTC")
    elif update:
        gap_data["update_str"] = str(update)

    if pro:
        pro_gap = abs(pro["points"][-1] - player["points"][-1])
        delta_pro = (
            pro_gap - abs(pro["points"][-2] - player["points"][-2])
            if len(player["points"]) >= 2 and len(pro["points"]) >= 2
            else 0
        )
        estimated_time_pro = (
            int((pro_gap) / (abs(delta_pro) * 4 / 60)) if delta_pro != 0 else 0
        )
        gap_data["pro"] = {
            "name": pro["name"],
            "rank": pro["ranks"][-1],
            "points": pro["points"][-1],
            "gap": pro_gap,
            "delta": delta_pro,
            "estimated_time": estimated_time_pro,
            "is_faster": delta_pro > 0,
        }

    if noob:
        noob_gap = abs(noob["points"][-1] - player["points"][-1])
        delta_noob = (
            noob_gap - abs(noob["points"][-2] - player["points"][-2])
            if len(player["points"]) >= 2 and len(noob["points"]) >= 2
            else 0
        )
        gap_data["noob"] = {
            "name": noob["name"],
            "rank": noob["ranks"][-1],
            "points": noob["points"][-1],
            "gap": noob_gap,
            "delta": delta_noob,
        }

    return gap_data


@app.route("/personal", methods=["GET", "POST"])
def personal_performance():
    region = getattr(request, "region", "GLB")
    player_id = request.cookies.get("player_id")

    if not player_id:
        return render_template("personal_login.html", region=region)

    region_cfg = get_region_config(region)
    db_path = region_cfg["DB_PATH"]
    if not os.path.exists(db_path):
        return render_template(
            "personal_performance.html",
            player=None,
            gap_data=None,
            stat_type="wins_pace",
            stat_types=[
                "wins_pace",
                "points_pace",
                "wins",
                "points",
                "points_wins",
                "ranks",
            ],
            players=[],
            manually_added_players=[],
            no_tournament=True,
            region=region,
        )

    conn = load_db_data(region)
    from cogs.utils import find_gap, find_player, time_data

    player = find_player(conn, player_id)
    if not player:
        conn.close()
        return render_template("personal_login.html", error="Player not found", region=region)

    if isinstance(player, list):
        player = player[0]

    # Get gap data
    pro, noob = find_gap(
        player, conn
    )  # Gets the player above and below the current player
    update, start, end, total, left, elapsed = time_data(region=region)

    # Get stat type from query params
    stat_type = request.args.get("type", "wins_pace")
    stat_types = ["wins_pace", "points_pace", "wins", "points", "points_wins", "ranks"]
    if stat_type not in stat_types:
        stat_type = "wins_pace"

    # Get players to compare (from query params)
    compare_ids = request.args.getlist("id")
    players = [player]
    manually_added_players = []  # Track only manually added players

    # Handle POST request for adding players
    if request.method == "POST":
        add_player_id = request.form.get("add_player_id")
        if add_player_id:
            compare_ids.append(add_player_id)

    # Add comparison players (only manually added ones)
    for compare_id in compare_ids:
        if compare_id != player_id:
            compare_player = find_player(conn, compare_id)
            if compare_player and isinstance(compare_player, dict):
                players.append(compare_player)
                manually_added_players.append(compare_player)

    # Handle include nearby players checkbox (temporary addition, not persisted)
    include_nearby = (
        request.args.get("include_nearby") == "true"
        or request.form.get("include_nearby") == "true"
    )
    if include_nearby:
        # Add the players above and below that we already have from find_gap
        nearby_players = []
        if pro:
            nearby_players.append(pro)
        if noob:
            nearby_players.append(noob)

        # Add nearby players to the players list (temporarily)
        players.extend(nearby_players)

    # Process gap data for template
    gap_data = process_gap_data(player, pro, noob, update)

    conn.close()

    # Redirect to GET with updated parameters to avoid form resubmission
    if request.method == "POST":
        params = {"type": stat_type}
        # Include all manually added players
        for player_obj in manually_added_players:
            params["id"] = player_obj["id"]
        if include_nearby:
            params["include_nearby"] = "true"

        return redirect(url_for("personal_performance", **params))

    return render_template(
        "personal_performance.html",
        player=player,
        gap_data=gap_data,
        stat_type=stat_type,
        stat_types=stat_types,
        players=players,
        manually_added_players=manually_added_players,
        chart_data_url=url_for(
            "chart_data_personal", type=stat_type, include_nearby=include_nearby
        ),
        region=region,
    )


@app.route("/set_player_id", methods=["POST"])
def set_player_id():
    player_id = request.form.get("player_id")
    if not player_id:
        return redirect(url_for("personal_performance"))

    response = make_response(redirect(url_for("personal_performance")))
    response.set_cookie("player_id", player_id, max_age=365 * 24 * 60 * 60)  # 1 year
    return response


@app.route("/logout", methods=["POST"])
def logout():
    """Clear user cookies and redirect to home"""
    response = make_response(redirect(url_for("leaderboard")))
    response.delete_cookie("player_id")
    return response


@app.route("/older_editions")
def older_editions():
    """Show available older editions"""
    region = getattr(request, "region", "GLB")
    editions = get_available_editions()
    return render_template("older_editions.html", editions=editions, region=region)


@app.route("/edition/<region>/<database>")
def edition_leaderboard_with_region(region, database):
    """Show leaderboard for a specific edition with explicit region"""
    if region not in ["GLB", "JP"]:
        return "Invalid region", 404
    
    # Set the region in request context
    request.region = region
    
    # Validate database parameter
    editions = get_available_editions()
    all_edition_names = []
    for region_editions in editions.values():
        all_edition_names.extend([e["filename"] for e in region_editions])
    
    if database not in all_edition_names:
        return "Edition not found", 404

    # Get leaderboard data using the specific database
    conn = load_db_data_with_database(database, region)
    if not conn:
        return "Database error", 500

    # Same logic as main leaderboard but with different database
    page = int(request.args.get("page", 1))
    type_param = request.args.get("type", "points")

    leaderboard_types = [
        "wins_pace",
        "points_pace",
        "wins",
        "points",
        "points_wins",
        "ranks",
    ]

    if type_param not in leaderboard_types:
        type_param = "points"

    # For older editions, calculate time data using the edition directory
    edition_dir = database.replace(".db", "")
    update, start, end, total, left, elapsed = time_data(
        update_only=True, tournament_over=True, edition_dir=edition_dir, region=region
    )
    current_hour = (
        71.26
        if elapsed is None
        else round(elapsed.days * 24 + elapsed.seconds / 3600, 2)
    )

    datatypes = {
        "wins_pace": "FLOAT",
        "points_pace": "FLOAT",
        "wins": "INTEGER",
        "points": "INTEGER",
        "points_wins": "FLOAT",
        "ranks": "INTEGER",
    }

    players_per_page = 10
    offset = (page - 1) * players_per_page

    # Use the same complex query as main leaderboard but with fixed hour
    conn.create_function("strrev", 1, lambda s: s[::-1])
    # Use ASC for ranks (lower is better), DESC for everything else
    order_clause = "ASC" if type_param == "ranks" else "DESC"
    query = f"""
        SELECT id, name,
               CAST(SUBSTR({type_param}, LENGTH({type_param}) - INSTR(strrev({type_param}), ',') + 2, LENGTH({type_param})) AS {datatypes[type_param]}) AS latest_type_value
        FROM players
        WHERE CAST(SUBSTR(hour, LENGTH(hour) - INSTR(strrev(hour), ',') + 2, LENGTH(hour)) AS FLOAT) > 0
        ORDER BY latest_type_value {order_clause}
        LIMIT ? OFFSET ?
    """

    cursor = conn.cursor()
    cursor.execute(query, (players_per_page, offset))
    players = cursor.fetchall()

    conn.close()

    return render_template(
        "leaderboard.html",
        players=players,
        page=page,
        type=type_param,
        leaderboard_types=leaderboard_types,
        current_edition=database,
        region=region,
    )

# Keep the old route for backward compatibility but redirect to new format
@app.route("/edition/<database>")
def edition_leaderboard(database):
    """Redirect old edition URLs to region-specific format"""
    region = getattr(request, "region", "GLB")
    return redirect(url_for('edition_leaderboard_with_region', region=region, database=database))


@app.route("/favicon.ico")
def favicon():
    return send_from_directory(
        app.static_folder, "favicon.ico", mimetype="image/vnd.microsoft.icon"
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port="2176")
