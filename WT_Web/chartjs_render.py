import json
import os
import sqlite3
import sys

sys.path.append(os.path.abspath(".."))
from cogs.utils import find_gap, find_player, load_db_data


def get_chart_data(
    player_id,
    stat_type,
    compare_ids=None,
    include_nearby=False,
    database=None,
    region="GLB",
):
    if region not in ["GLB", "JP"]:
        region = "GLB"
    if database and database != "None":
        # For older editions, the database is in the edition directory
        edition_name = database.replace(".db", "")  # Remove .db extension if present
        db_path = os.path.join(
            "..", "older_editions", region, edition_name, f"{edition_name}.db"
        )
        if not os.path.exists(db_path):
            return {"error": "Database not found"}
        conn = sqlite3.connect(db_path)
    else:
        db_path = os.path.join("..", "instances", region, "database.db")
        conn = sqlite3.connect(db_path)
    players = []
    print(f"Trying to find player at {db_path}")
    main_player = find_player(conn, player_id)
    players.append(main_player)

    if compare_ids:
        for compare_id in compare_ids:
            if compare_id != player_id:
                compare_player = find_player(conn, compare_id)
                if compare_player:
                    players.append(compare_player)
                    print(f"  Added comparison player: {compare_player['name']}")
                else:
                    print(f"  Comparison player {compare_id} not found!")

    if include_nearby and main_player:
        pro, noob = find_gap(main_player, conn)
        if pro:
            players.append(pro)
            print(f"  Added nearby player (above): {pro['name']}")
        if noob:
            players.append(noob)
            print(f"  Added nearby player (below): {noob['name']}")

    print(f"  Total players: {len(players)}")
    for i, p in enumerate(players):
        print(
            f"    {i+1}. {p['name']} - {stat_type}: {len(p[stat_type]) if stat_type in p else 'N/A'} points"
        )

    conn.close()

    datasets = []
    colors = ["#FF6384", "#36A2EB", "#FFCE56", "#4BC0C0", "#9966FF", "#FF9F40"]

    for i, player in enumerate(players):
        color = colors[i % len(colors)]

        data_points = []
        for j, hour in enumerate(player["hour"]):
            if j < len(player[stat_type]):
                data_points.append({"x": hour, "y": player[stat_type][j]})

        datasets.append(
            {
                "label": player["name"],
                "data": data_points,
                "borderColor": color,
                "backgroundColor": color + "20",
                "tension": 0.1,
                "pointRadius": 3,
                "pointHoverRadius": 6,
                "fill": False,
            }
        )

    chart_config = {
        "type": "line",
        "data": {"datasets": datasets},
        "options": {
            "responsive": True,
            "maintainAspectRatio": False,
            "plugins": {
                "title": {
                    "display": True,
                    "text": f'{stat_type.replace("_", " ").title()} over Time',
                    "font": {"size": 16},
                },
                "legend": {
                    "position": "top",
                    "labels": {"usePointStyle": True, "padding": 20},
                },
            },
            "scales": {
                "x": {
                    "type": "linear",
                    "title": {"display": True, "text": "Hour", "font": {"size": 14}},
                    "ticks": {"font": {"size": 12}},
                },
                "y": {
                    "type": "linear",
                    "title": {
                        "display": True,
                        "text": stat_type.replace("_", " ").title(),
                        "font": {"size": 14},
                    },
                    "ticks": {"font": {"size": 12}},
                    "reverse": stat_type
                    == "ranks",  # Invert y-axis for ranks (lower is better)
                },
            },
        },
    }

    return chart_config
