import os
from datetime import timedelta, timezone

BOT_TOKEN = ""
API_TOKEN = ""
WT_EDITION = 61
USER_AGENT = ""

BOTS = {
    "GLB": {
        "WT_EDITION": 61,  # placeholder, update manually when needed
        "DB_PATH": os.path.expanduser("~/Dokkan/instances/GLB/database.db"),
        "FETCH_PATH": os.path.expanduser("~/Dokkan/instances/GLB/fetches"),
        "USER_AGENT": USER_AGENT,
        "UPDATE_TOKEN": "whatever",
        "API_BASE_URL": "http://127.0.0.1:8765",
        "TIMEZONE": timezone.utc,  # UTC+0 for GLB
    },
    "JP": {
        "WT_EDITION": 55,  # placeholder, update manually when needed
        "DB_PATH": os.path.expanduser("~/Dokkan/instances/JP/database.db"),
        "FETCH_PATH": os.path.expanduser("~/Dokkan/instances/JP/fetches"),
        "USER_AGENT": USER_AGENT,
        "UPDATE_TOKEN": "whatever",
        "API_BASE_URL": "https://jpn.dokkan.wiki",  # Yeah I know
        "TIMEZONE": timezone(timedelta(hours=9)),  # UTC+9 for JP
    },
}
