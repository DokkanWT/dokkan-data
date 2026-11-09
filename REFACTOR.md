# REFACTOR — Splitting Dokkan into independent services

Status: **draft for review** (no code changed yet)
Scope: separate fetching, website, and Discord bot into independently deployable,
containerized services with a shared core library. Everything runs on one Docker host.

## 1. Decisions

| Topic | Decision |
|---|---|
| Repos | 3 repos (see §3) |
| Fetching | 2 containers from the same image (`WT_REGION=GLB` / `JP`) |
| Deployment | `docker compose` |
| Hosts | **One** Docker host (the existing machine), behind the existing reverse proxy |
| Database location | Host dir `~/Dokkan/data/<REGION>/<edition>/` bind-mounted at `/data`; never mounted into `web`/`bot` |
| DB access | Read-only HTTP data service container; ingest writes locally |
| Change notification | Monotonic `revision` in `metadata.json`, polled by the web app |
| DB engine | SQLite for now, behind a backend interface (Postgres later, not now) |
| Reuse in the bot | Small wrapper objects (resolver, renderer, link store, response helpers) — only where duplication is mechanical; no framework, no generic command generator (§6.9) |
| Where wrappers live | Pure data/resolution types in `dokkan_core`; anything touching `discord.ui`/`discord.File` in `dokkan-bot` |
| Failure signalling | Tagged return values (`Resolution(kind=...)`), not exceptions |
| `output_dir` graphs | Still written to disk for now; in-memory `BytesIO` + LRU cache stays a follow-up (`TODO`) |
| Local workspace | `~/Dokkan/{dokkan-data,dokkan-web,dokkan-bot}` already created (§3.1) |
| Host data dir | `~/Dokkan/data/<REGION>/<edition>/`, bind-mounted at `/data`; no hardcoded filesystem paths anywhere (§5, §6.3) |
| Repo history | No rewrite: repo A keeps its existing remote and commits; B/C are fresh `git init` (§3) |
| Current WT edition | Manual `<REGION>_WT_EDITION` env var, bumped by hand a few times a year |
| Tests | Per repo, covering that repo's own behaviour; no cross-repo test suite (§6.1) |
| Secrets | **Docker secrets** (files in `/run/secrets`), not env vars (§6.3) |
| Backups | None automated. Raw fetch JSONs are archived by hand into `../WT_Archive/RawData`, which is enough to rebuild any DB (§3.1) |
| Legacy `/api/*` routes | External consumers exist → keep byte-identical, do not version (§6.7) |
| Nix | Local devshell only (trimmed); containers do not use it (§6.11) |
| Core distribution | Wheel on a `core-v*` GitHub Release of repo A, pinned `~=X.Y` (§8.1) |
| CI | GitHub Actions, one workflow per repo (§8.1) |

Rationale for the data service: everything runs on one machine, so this is no longer
about SQLite over NFS. The HTTP boundary is kept because it (a) keeps `sqlite3` out of
`web`/`bot` entirely (enforced in §8), (b) is the single place that opens the
per-edition databases (`/data/<REGION>/<edition>/database.db`), and (c) keeps a later
data/app host split cheap. The cost is one network hop on the compose network.

## 2. Target topology

Everything runs in **one** `docker compose` project on the existing machine. Only `web`
is published; the reverse proxy in front of it is the operator's responsibility.

```
┌────────────────────────── ONE DOCKER HOST ──────────────────────────┐
│                                                                     │
│  ingest-glb ──┐                          web (Flask, :2176) ◄───────┼── reverse proxy
│               ├──► /data (rw)                  ▲                    │   (operator)
│  ingest-jp ───┘      ▲   ▲   ▲                 │                    │
│                      │   │   └──── DATANET ────┴──► bot             │
│                      │   └──────► dataservice                       │
│                      │           (FastAPI, ro, :8000, unpublished)  │
└─────────────────────────────────────────────────────────────────────┘
   bind mount:  ~/Dokkan/data  ->  /data   (SQLite + fetches + editions)
```

- One writer (ingest), one reader service (`dataservice`), reached over the compose
  network as `http://dataservice:8000` — **no published port**.
- Web and bot contain **no** `sqlite3` imports and no filesystem knowledge of the data;
  neither mounts the database directories (§5).
- Web keeps its existing public routes; they are backed by the data service.
- `bot` mounts only its own subtree (`/data/bot`) for `discord_users.json` + graph cache,
  never the databases.

## 3. Repo split

| Repo | Contents | Trust |
|---|---|---|
| **A. `dokkan-data`** | `core/` (`dokkan_core`), `ingest/`, `dataservice/`, `compose.yaml` | private |
| **B. `dokkan-web`** | `WT_Web/` app, templates, static, `Dockerfile` | can be public |
| **C. `dokkan-bot`** | `cli_main.py`, `cogs/`, `render.py`, `Dockerfile` | can be public |

Repo mechanics:

- **No history rewrite.** Repo A *is* the existing `DokkanWTBot` repository — same
  remote (`git@github.com:polowiper/DokkanWTBot.git`), same commits. Its local
  directory is `~/Dokkan/dokkan-data`. It is updated in place; nothing is filtered
  out, and there is **no** `git filter-repo` / `git subtree split` step.
- **Repos B/C start empty**: fresh `git init` + first commit once their code lands
  (§7). No shared history with A, no submodules.
- `dokkan_core` reaches B/C as a **wheel** pinned in their requirements. A wheel keeps
  Docker builds free of SSH keys and of `COPY ../..` build-context tricks.

`core` lives in repo A (3 repos, §12.1). The wheel is built by Actions and attached to
a `core-v*` GitHub Release; B/C download it with a `CORE_WHEEL_TOKEN` secret (§8.1).

### 3.1 Local workspace (already created, do not re-create)

The three target directory roots already exist side by side:

```
~/Dokkan/
  dokkan-data/     # repo A — this tree; becomes core/ + ingest/ + dataservice/
  dokkan-web/      # repo B — created, empty
  dokkan-bot/      # repo C — created, empty
  WT_Archive/      # OUT OF SCOPE — archive of older edition fetches only
```

Rules for the workspace:

- **`../dokkan-web/` and `../dokkan-bot/` exist and are empty.** Step §7.7 fills them;
  nothing in this plan may re-create them, rename them, or nest them inside repo A.
  They have no git repo, remote, or CI yet (§7.7, §8.1).
- **`../WT_Archive/` is completely unrelated to this refactor.** It is where you archive
  older edition fetches by hand (`RawData/`), which is also the de-facto backup: any
  database can be rebuilt from it. The refactor adds **no** automation for it and **no**
  code path may read or write it — it must not appear in any `.dockerignore`, compose
  volume, bind mount, bootstrap script, grep gate, or golden fixture, and no path in this
  document may be repointed to it. Copying fetches there stays a manual operator step.
- Relative paths in this document are therefore: repo A = `~/Dokkan/dokkan-data`,
  repos B/C = `~/Dokkan/dokkan-web` / `~/Dokkan/dokkan-bot`.

Current on-disk state relevant to the plan:

| Path (relative to repo A) | Size | In git? | Fate |
|---|---|---|---|
| `instances/GLB/` | 1.2 GB | no (gitignored) | copied to `~/Dokkan/data/GLB/<WT_EDITION>/` by bootstrap (§6.11); original deleted at §7.9 |
| `older_editions/GLB/<n>/` | 1.1 GB | no (gitignored) | copied to `~/Dokkan/data/GLB/<n>/` — same tree, one dir per edition (§5); original deleted at §7.9 |
| `./database.db` | 108 MB | no | **stale** — deleted at the end of rollout (§7.9), not now |
| `top100_data/` | 524 KB | no | bot graph cache, replaced by `/data/bot/cache` |
| `discord_users.json` | 2 KB | **yes, committed** | copied to `/data/bot/` by bootstrap, then `git rm`'d (history kept, §6.9.6) |
| `config.py.local` | 1 KB | no | rotate + delete (§6.3) |

Data lives **outside** the repos. The host data directory is `~/Dokkan/data`,
bind-mounted at `/data`, and is laid out as `<REGION>/<edition>/` (current edition and
archived editions side by side); the full layout is in §5. Note that `config.py`'s current
values (`~/Dokkan/instances/...`, `~/Dokkan/older_editions/...`) are **already stale**:
they point at the pre-move `~/Dokkan`, which is now only the parent of the three repo
directories. Nothing may be repointed at those paths; after §6.3 the env
vars/`core/paths.py` are the only source of filesystem paths.

Three facts that constrain the bootstrap step (§6.11): `instances/JP/` is currently
**empty** (JP fetching has been broken upstream for the last editions — the refactor
must still keep JP fully supported), the root `database.db` is not the live one, and
no automated job archives fetches into `../WT_Archive/RawData` — that is done by hand
and stays that way.

## 4. Current coupling (why this refactor)

**Shared code**
- `cogs/utils.py` is the de-facto core library but lives inside the bot package.
  Imported by the fetcher (`fetch_and_save.py:10`, `update_db.py:10`) and the
  website (`WT_Web/app.py:17`, `WT_Web/chartjs_render.py:7`).
- `cogs/utils.py:7` imports `config` (`BOTS`, `USER_AGENT`, `WT_EDITION`) at module
  scope, so importing any shared helper drags in secrets.
- `config.py` mixes bot token, API token, WT edition, DB paths, notify tokens, timezones.
- `cogs/predict.py:4` and `WT_Web/app.py:16` both use `sys.path.append("..")`.

**Hardcoded paths**
- `cogs/utils.py:21` `../top100_data`, `:247` `../discord_users.json`, `:35` `../older_editions`.
- `render.py:18` global `output_dir = "top100_data"` created at import; cogs read
  images back from it (`pace.py:39`, `points.py:52`, `seed.py:36`, …).
- `cogs/compare.py:42`, `cogs/compareme.py:42` hardcode `../older_editions/GLB`.
- `cogs/predict.py:18,51` uses `ROOT_DIR` instead of `OLDER_EDITIONS_PATH`.
- `cogs/fetches_count.py:30` reads `"fetches"` (already broken).
- `WT_Web/chartjs_render.py:24,30` hardcodes `../older_editions/...` and
  `../instances/<region>/database.db`, ignoring `DB_PATH`, and opens read-write.
- `WT_Web/app.py:185,230,661,673` hand-builds `..` paths.
- Admin scripts hardcode `instances/<region>/...` (`manual_update.py:318`,
  `manual_update_steroids.py:328`, `sort_fetches.py:183`, `check_glb_updates.py:12`).

**Runtime coupling**
- `update_db.py:365-378` POSTs to the web app (`127.0.0.1:2176/notify_update`).
- `WT_Web/notify.py` is a duplicate with a hardcoded token.
- Bot `time_data()` falls back to reading fetcher JSON (`cogs/utils.py:421`).
- Web region detection is hostname-based (`app.py:41`, `jpn.` prefix), which breaks
  behind a container reverse proxy.

**Bot-internal duplication (why §6.9)**
- 13 commands repeat the same identifier → rank → link → find → disambiguate
  prelude (`pace.py:141`, `wins.py:87`, `points.py:141`, `max.py:73`, `seed.py:108`,
  `rseed.py:88`, `ranking.py:34`, `gap.py:41`, `when.py:105`, `target.py:88`,
  `highest.py:34`, `predict.py:55`, `bulk.py:138`), each with its own copy of the
  messages and its own handling of `find_player` returning a dict *or* a list.
- ~10 near-identical `PlayerSelect`/`PlayerSelectView` classes (`pace.py:12`,
  `wins.py:13`, `points.py:12`, `seed.py:13`, `rseed.py:11`, `gap.py:87`,
  `when.py:12`, `target.py:12`, `bulk.py:31`, `compare.py:203`, `compareme.py:216`)
  plus two inline ones (`max.py:95`, `ranking.py:63`) and a fourth variant in
  `finduser.py:41`.
- 21 copies of the `Updated at` embed field, 14 copies of the `2005-03-30`
  fallback, 15 copies of the `except → "Me no worki"` handler, 21 autocomplete
  stubs, 9 hand-built graph paths next to 4 more inside `render.py`.
- `compare.py:110` and `compareme.py:115` keep per-request state on the cog
  singleton, so overlapping invocations corrupt each other.

**Dead / legacy**
- `api.py` (old Flask API, same port 2176, hardcoded `database.db` / `./fetches`) —
  superseded by `WT_Web`.
- `main.py` (tkinter UI, self-described abandoned).
- `update_data.py`, `final_render.py` (one-off, hardcoded DB/hours).
- Root `database.db`, `config.json`.

## 5. Target layout

```
dokkan-data/                     # repo A (trusted)
  core/dokkan_core/
    settings.py    # env-driven Settings / RegionSettings
    paths.py       # the ONLY place with filesystem defaults
    queries.py     # all SQL (moved out of cogs + WT_Web)
    models.py      # Player / Border / Edition / Status / TimeInfo
    players.py     # PlayerRef / Resolution / resolve_player (discord-free, §6.9.2)
    local.py       # SqliteBackend (dataservice + ingest containers only)
    client.py      # DataClient (HTTP; used by web + bot)
    backend.py     # Protocol implemented by local + client
    errors.py
  ingest/
    fetch_and_save.py
    update_db.py
    admin/         # convert_to_older, create_edition_fetches, manual_update*,
                   # sort_fetches, check_glb_updates, final_render, test_time_*
  dataservice/
    app.py         # FastAPI read-only API
  compose.yaml     # single host, compose profiles: data / app / admin
  Dockerfile.ingest
  Dockerfile.dataservice

dokkan-web/                      # repo B
  app.py, chartjs_render.py, templates/, static/
  Dockerfile

dokkan-bot/                      # repo C
  cli_main.py
  cogs/
  render.py        # pure matplotlib: no paths, no discord, called only by rendering.py
  players.py       # PlayerCommand: resolve + disambiguate + embed + reply   (§6.9.3)
  ui.py            # the one PlayerSelectView                               (§6.9.4)
  rendering.py     # GraphRenderer / Graph (cache dir, filenames, File)     (§6.9.5)
  storage.py       # DiscordLinkStore                                      (§6.9.6)
  responses.py     # updated_field, reply_error, shared choice constants    (§6.9.7)
  tools/
    migrate_links.py  # one-shot discord_users.json free-text → player ids (§6.9.6)
  Dockerfile
```

Data layout — host `~/Dokkan/data`, bind-mounted at `/data`. **One directory per
edition**, current and archived side by side; the edition number is the directory name.

```
/data/GLB/63/{database.db,metadata.json,fetches/}                <- current (writable)
/data/GLB/62/{database.db,metadata.json,first.json,latest.json}  <- archived (read-only)
/data/GLB/55/...  /data/GLB/56/...  /data/GLB/57/...
/data/JP/55/{database.db,metadata.json,fetches/}                <- current (writable)
/data/JP/56/...  /data/JP/57/...                                <- archived (read-only)
/data/bot/{discord_users.json,cache/<region>/<edition>/<player id>/<kind>.png}
```

- **The database file is always `database.db`**, current and archived alike. Today's
  archive uses `<edition>.db`; `bootstrap` and `convert_to_older.py` normalise to
  `database.db`, so `paths.db_path(region, edition)` has exactly one rule.
- `<REGION>_WT_EDITION` names the **current** edition and therefore the only directory a
  region's ingest may write to. Every other `<n>` is an archived edition: read-only for
  everyone, produced by `ingest/admin/convert_to_older.py`.
- `edition=0` in the API means "current"; every other value is a directory name.
- Archived edition dirs hold `database.db` + `metadata.json` + `first.json` +
  `latest.json`, and **no `fetches/`** (verified on disk). Only the current edition has
  `fetches/`.
- Edition numbers are **per region**: `GLB/55` and `JP/55` are unrelated and may both
  exist. Nothing may ever build a path from an edition number without a region.
- `/data/bot` is not region/edition-scoped: bot state only (link store + PNG cache); the
  cache nests `<region>/<edition>/<player id>/` because graph keys are per edition.
- No container writes outside its own subtree; `core/paths.py` derives every path from
  `DATA_ROOT` + region + edition.

**The working directory can hold an already-archived edition.** `<REGION>_WT_EDITION`
names the edition being fetched, but between tournaments it may name one that is already
archived — true on this disk today: `older_editions/GLB/63/` exists while
`instances/GLB/` still holds a 956 MB leftover working copy of edition 63 (DB + 290
fetch files) that you meant to delete after archiving. Rules:

- **The archive is authoritative.** Any edition present in `older_editions/<REGION>/<n>/`
  is seeded from there, period.
- `instances/<REGION>/` is only the **in-progress working directory** of the edition
  currently being fetched. It seeds `data/<REGION>/<WT_EDITION>/` **only if**
  `<WT_EDITION>` is not already archived; otherwise it is a leftover and is skipped
  (the bootstrap reports it, and §7.9 deletes it).
- **An archived edition dir is immutable**: it contains `first.json`/`latest.json` and no
  `fetches/`. A live dir contains `fetches/` and no `first.json`. Ingest refuses to write
  into an archived dir and exits with "edition `<n>` is already archived, bump
  `<REGION>_WT_EDITION`" instead of silently mutating a frozen edition.
- The two edition-63 DBs are **not** byte-identical (same 37,541 players / 11 borders,
  different SHA-256), so nothing may assume the archive copy equals the leftover — the
  archive copy always wins (§12.3).

| Container | Mount | Mode |
|---|---|---|
| `ingest-glb` | `/data/GLB` | rw |
| `ingest-jp` | `/data/JP` | rw |
| `dataservice` | `/data` | ro |
| `admin` (one-shot) | `/data` | rw |
| `bot` | `/data/bot` | rw |
| `web` | none | — |

The graph cache is laid out as `<cache>/<region>/<edition>/<player id>/<kind>.png`
(ids, not names — §6.9.5) under `/data/bot/cache`.

## 6. Work plan

### 6.1 Baseline
1. Snapshot `instances/` + `older_editions/` to a temp dir.
2. Record golden outputs: web `/`, `/api/get-top100`, `/api/get-user`,
   `/api/<n>/metadata`, `/player`, `/chart_data`; bot `/pace`, `/compare`,
   `/predict`, `/leaderboard`, `/when`.
3. Add golden tests, diffed against the new implementation at every step.
4. Tests are **per repo**, covering only that repo's behaviour: repo A owns
   `core` + `dataservice` contract tests (with a small trimmed fixture DB), repo B owns
   the web route/JSON tests (recorded fixtures or a run against the dataservice), repo C
   owns the bot tests (resolver, views, rendering, store — no Discord connection needed).
5. The fixture DB lives in repo A only, trimmed to a few players including a
   duplicate-name pair; B/C consume recorded JSON/PNG fixtures, never a database.

### 6.2 `dokkan_core`
1. Move out of `cogs/utils.py`: `get_region_config`, `load_db_data`, `find_rank`,
   `find_player`, `format_player`, `find_borders`, `find_gap`, `find_best`,
   `latest_fetch`, `first_fetch`, `time_data`.
2. Move every duplicated SQL string into `core/queries.py` (`cogs/utils.py`,
   `WT_Web/app.py` leaderboard/top100/max-hour queries, `chartjs_render.py`,
   `cogs/predict.py`). This is the single home for the `strrev`/`SUBSTR` tricks.
3. Preserve return shapes (`time_data` 6-tuple, `find_player` dict-or-list) so downstream
   edits stay small **for step 6.2 only**. §6.9 deliberately replaces the
   dict-or-list contract with a tagged `Resolution`, so do not harden it further.
4. Keep `discord`, `flask`, `matplotlib`, and `load_discord_users` out of `core`.

### 6.3 Settings (`core/settings.py`)
Env contract:
```
DATA_ROOT=/data     # the only path root; every other path is derived (§5)
WT_REGIONS=GLB,JP
<REGION>_WT_EDITION, <REGION>_API_BASE_URL, <REGION>_TZ (IANA), <REGION>_USER_AGENT
DATA_API_URL         # web/bot only (http://dataservice:8000)
BOT_DATA_DIR         # bot only (/data/bot)
DEFAULT_REGION, WEB_PORT, WEB_SSE_POLL_SECONDS, DATA_API_TIMEOUT
```
Secrets are **Docker secrets**, mounted as files and never put in the image or in a
compose `environment:` block:
```
/run/secrets/bot_token        -> cli_main.py
/run/secrets/api_token        -> ingest (upstream fetch API)
/run/secrets/data_api_token   -> dataservice + web + bot
```
- `core/settings.py` exposes one `read_secret(name)` helper (file first, env var
  fallback for local dev via the Nix shell / `config.py.local`).
- Timezones are IANA names resolved with `zoneinfo` (env vars can't hold tzinfo).
- `core/paths.py` exposes `region_dir(region)`, `edition_dir(region, edition)`,
  `db_path(...)`, `fetch_dir(...)`, `cache_dir(...)` and takes `DATA_ROOT` from settings.
  There are **no** per-file path env vars any more (`*_DB_PATH`, `*_FETCH_PATH`,
  `*_OLDER_EDITIONS_PATH` are gone); local dev only overrides `DATA_ROOT`.
- `<REGION>_WT_EDITION` stays a **manual** value: the operator edits it and restarts
  the two ingest containers when a new WT starts (a few times per year).
- `config.py` remains as a deprecated shim until the final cleanup.
- Rotate `BOT_TOKEN` / `API_TOKEN` while moving them to secrets: `config.py.local`
  currently contains live values.

### 6.4 Backend interface
`backend.py` Protocol:
```python
get_status(region) -> Status
list_editions(region) -> list[Edition]
leaderboard(region, edition, stat, page, per_page) -> list[Player]
find_players(region, identifier, edition) -> list[Player]
search_players(region, q, edition, limit)
random_player(region, edition)
player_by_rank(region, rank, edition)
player_by_id(region, player_id, edition)
players_by_ids(region, ids, edition)          # bulk
top100(region, edition)                       # bulk
gap(region, player_id, edition) -> {player, above, below}
borders(region, rank_or_all, edition)
best_across_editions(region, player_id)
predict(region, player_id=None, rank=None)
chart_series(region, ids, stat, edition, include_nearby)
```
- `local.SqliteBackend` implements it against SQLite (dataservice/ingest only).
- `client.DataClient` implements it over HTTP (web + bot import only this).
- **`edition=0` (the default everywhere) means "the current edition"**, resolved from
  `<REGION>_WT_EDITION` → `/data/<REGION>/<WT_EDITION>/database.db`. Any other value is
  an archived edition → `/data/<REGION>/<edition>/database.db`; a missing edition
  directory is a typed `not_found`, never a fallback to the current DB.
- Endpoints return **numbers and records only** — no user-facing prose (the bot owns the
  wording, the web owns its templates).

### 6.5 Data service (FastAPI)
```
GET /v1/health
GET /v1/regions
GET /v1/status/{region}                         ETag: "<region>:<revision>"
GET /v1/editions/{region}
GET /v1/leaderboard/{region}?edition=&stat=&page=&per_page=
GET /v1/players/{region}/{identifier}?edition=
GET /v1/players/{region}/search?q=
GET /v1/players/{region}/random?edition=
GET /v1/players/{region}/by-rank?rank=&edition=
GET /v1/players/{region}/bulk?ids=1,2,3&edition=
GET /v1/players/{region}/top100?edition=
GET /v1/players/{region}/{id}/gap?edition=
GET /v1/players/{region}/{id}/best
GET /v1/borders/{region}?rank=100|all&edition=
GET /v1/predict/{region}?id=|rank=
GET /v1/chart/{region}?ids=&stat=&edition=&include_nearby=
```
- Bulk endpoints are required: `WT_Web/app.py:get_top100_users` currently does one
  `get_user_by_identifier` call per player; over HTTP that is 100 round-trips.
- Auth: `Authorization: Bearer $DATA_API_TOKEN`; TLS via reverse proxy.
- LRU cache keyed by `(region, edition, revision)` for status/leaderboard/editions.
- `predict` and `chart` run server-side so the bot makes one call, not N×editions.
- `predict` returns **numbers only** (points, target, projection, deltas); the bot owns
  the embed wording. Same rule for every endpoint: core and the data service never
  return user-facing prose.

### 6.6 Ingest
1. `fetch_and_save.py`: use `core.settings`; write `fetch<N>.json`, `config.json`,
   `metadata.json` atomically (`tmp` + `os.replace`).
2. `update_db.py`: use `core.local`; enable `journal_mode=WAL`, `busy_timeout`,
   `synchronous=NORMAL`; after commit bump `metadata.revision` atomically.
   **Delete** the `notify_update` POST (`update_db.py:365-378`).
3. Admin scripts import `core.paths`/`core.settings`, no `instances/...` or
   `older_editions/...` literals; `convert_to_older.py` and
   `create_edition_fetches.py` write into `/data/<REGION>/<edition>/`.
4. Admin tools live in the ingest image under an `admin` entrypoint.
5. Delete `update_data.py` and root `config.json` now. **Keep** root `database.db`,
   `instances/` and `older_editions/` (and their `.gitignore` entries) until the
   containers are proven; the final deletion happens in §7.9.
6. Keep `final_render.py`, `test_time_glb.py`, `test_time_jp.py`, `manual_update*.py`,
   `convert_to_older.py` and `WT_Web/create_edition_fetches.py` (moved here from repo B)
   as `admin` entrypoints — some are unused today, but they stay runnable in the ingest
   image instead of being deleted.

### 6.7 Web
1. Remove `sys.path.append("..")`, `from cogs.utils`, `from config`.
2. Inject `DataClient`; replace `load_db_data`/raw SQL; keep public routes and JSON
   shapes identical (verified by the golden tests).
3. `chartjs_render.py` calls `/v1/chart/...`; drop `sqlite3` and path literals.
4. SSE: background thread polls `/v1/status/{region}`, broadcasts on `revision`
   change. Remove `/notify_update` and `WT_Web/notify.py`.
5. Region routing: `?region=` first, `DEFAULT_REGION` env, then the proxy hostname as a
   fallback. `dokkan-wt.info` = GLB, `jpn.dokkan-wt.info` = JP, and both must keep
   working — the app must not *depend* on the hostname (external consumers and the
   `?region=` query string are equally supported).
6. `app.run` host/port from env (fix the string port).
7. Remove the duplicate `process_gap_data` and unused imports.

### 6.8 Bot
1. Delete `cogs/utils.py`; move `load_discord_users`/`save_discord_users` into
   `storage.DiscordLinkStore` using `BOT_DATA_DIR` (§6.9.6).
2. Replace `from cogs.utils import *` with explicit `dokkan_core` imports; replace
   the global `output_dir` with `paths.cache_dir()`.
3. `render.py`: cache dir from env. **Delete GIF support** (`animate`,
   `FuncAnimation`, `PillowWriter`) — nothing but the abandoned `main.py` used it.
   Make `render()`/`bulk_render()` reachable only through `rendering.GraphRenderer`
   (§6.9.5). Keep writing PNGs to disk for now; `BytesIO` + LRU/TTL cache stays the
   `TODO` follow-up (key: region, edition, ids, type, borders, revision).
4. `compare.py`, `compareme.py`, `predict.py`: replace raw `sqlite3` /
   `../older_editions/GLB` / `ROOT_DIR` with client calls.
5. `fetches_count.py`: use `/v1/status` or `/v1/editions`.
6. `cli_main.py`: `BOT_TOKEN` from env; keep `os.listdir("./cogs")`
   (`WORKDIR /app/bot`).
7. `time_data()` → `client.get_status()`, rebuilding aware datetimes from
   epoch + IANA tz so `<t:...>` timestamps keep working.
8. Collapse the 13 identifier-resolution preludes into `PlayerCommand` (§6.9.3) and
   delete every local `PlayerSelect`/`PlayerSelectView` (§6.9.4), one command per
   commit, golden-diffed.
9. Move per-request state off the cog singletons (`compare.py:110`,
   `compareme.py:115`); `resolved_users`/`unresolved_users` belong on the
   per-invocation object.
10. `/link` reads back the candidates and lets the user pick the exact player
    (label shows `#rank name` and the player id), then stores the **player id**.
    Existing free-text values are converted once by `tools/migrate_links.py`
    (§6.9.6); the resolver keeps tolerating free text for whatever the script
    leaves for a human (id → exact name → `LIKE`).
11. `/predict` and `/highest` adopt the selection menu instead of erroring/branching
    on the wrong shape.
12. Audit the remaining cogs for a missing menu — expected final list:
    `pace, wins, points, max, seed, rseed, ranking, gap, when, target, highest,
    predict, bulk, compare, compareme, link`.

> The wrappers in §6.9 are what makes items 1–11 small. Do not hand-edit 16 cogs
> first and abstractions later; that is the double rewrite.

### 6.9 Bot reuse layer — classes worth writing

The duplication below was counted on the current tree, not guessed.

| Reused thing | Copies today |
|---|---|
| identifier → rank → link → find → disambiguate → not-found/too-many prelude | **13** |
| `PlayerSelect` + `PlayerSelectView` | **~10**, all slightly different |
| `embed.add_field("Updated at", "<t:…:f> (<t:…:R>)")` | **21** |
| `datetime.fromisoformat("2005-03-30")` fallback | **14** |
| `os.path.join(output_dir, name.replace("$", "\\$"), f"{type}.png")` + `os.path.exists` | **9** (+4 in `render.py`) |
| `except → log` + `"Me no worki lol ask Polo"` | **15** |
| `region` / `borders` / wins-points autocompletes | **11 / 6 / 4** |
| `find_borders(conn, 100) if borders == "1" else None` | **8** |

| Wrapper | Repo / file | Replaces | Payoff |
|---|---|---|---|
| `Resolution` + `resolve_player` | A · `core/dokkan_core/players.py` | 13 preludes, `find_player` dict-or-list | testable, uniform, fixes rank/link bugs |
| `PlayerCommand` | C · `bot/players.py` | the 60-line prelude + the embed/reply tail | cogs drop to ~50 lines |
| `PlayerSelectView` | C · `bot/ui.py` | ~10 select classes | one author check, one label format |
| `GraphRenderer` / `Graph` | C · `bot/rendering.py` | path building + `os.path.exists` + `$` escaping | one cache dir, one filename rule |
| `DiscordLinkStore` | C · `bot/storage.py` | `load/save_discord_users` (13 read sites) | atomic, race-free |
| `responses.py` helpers | C · `bot/responses.py` | 21 + 15 + 21 copies | one format, one error path |

#### 6.9.1 Rule of thumb

Write the class when the duplication is **mechanical**: same lines, same message,
same filename rule, same failure handling. Do not write it when the call sites
differ in wording, colour, control flow, or maths — that is where a wrapper becomes
"more complicated for no real benefit".

Explicit non-goals (do not do these):
- **No generic command generator.** `@app_commands.describe` text, embeds, and
  outputs are per-command; generating slash commands from config trades 50 clear
  lines for an opaque table.
- **No shared embed design system.** Titles/colours/descriptions stay local.
- **No `discord` import in `dokkan_core`.** The resolver returns data; the bot turns
  it into a `View`. §6.2 rule 4 still holds.
- **`finduser` keeps its own fuzzy search.** `%P%o%l%o%` is a discovery tool, not an
  identity resolution — it returns candidates only, never a single player.
- **`leaderboard`, `ties`, `fetches_count`, `help` are out of scope.** They never
  resolve a player.
- **Do not re-wrap `DataClient`** behind another service layer.
- **Do not share the renderer with the web.** `WT_Web` uses Chart.js;
  `render.py:6`'s `WT_WEB_RENDER` switch is vestigial and can go.

#### 6.9.2 Player resolution (`dokkan_core/players.py`)

```python
@dataclass(frozen=True)
class PlayerRef:                      # cheap, stable, JSON-able
    id: int
    name: str
    rank: int | None
    region: str
    edition: int = 0

@dataclass(frozen=True)
class Resolution:                     # tagged result, not exceptions
    kind: Literal["player", "ambiguous", "not_found", "not_linked", "too_many"]
    player: dict | None = None
    candidates: tuple[PlayerRef, ...] = ()
    identifier: str | None = None

def resolve_player(client, *, region, edition=0, identifier=None, rank=None,
                   linked_identifier=None, max_candidates=25) -> Resolution: ...
```

- A **tagged return value**, not exceptions: each `kind` maps to a different user
  message, and the whole thing unit-tests against a fake backend.
- The caller passes `linked_identifier=store.get(interaction.user.id)`; core never
  learns that `discord_users.json` exists (§6.2 rule 4).
- Order: `rank` → `client.player_by_rank()`, else `identifier` or `linked_identifier` →
  `client.find_players()`, then classify: 0 → `not_found`, 1 → `player`,
  `> max_candidates` → `too_many`, else `ambiguous`.
- If neither `identifier` nor `linked_identifier` is given, the result is
  `not_linked` — the "link your account (/link)" message is written once, in the
  bot, keyed off `kind`.
- Owning rank resolution here removes a real inconsistency: `rank` is passed as `str`
  almost everywhere, as `int` in `rseed.py:71`, and `region`/`edition` are silently
  dropped by most call sites (`pace.py:170` passes them, `wins.py:102` does not).
- Numeric-identifier caveat: after §6.8.10 stores player ids, an all-digit *name*
  would be tried as an id first. On `not_found` with `identifier.isdigit()`, retry
  once as an exact-name match.

#### 6.9.3 `PlayerCommand` (bot repo, `players.py`)

A **per-invocation** object (never stored on the cog — see §6.9.8):

```python
cmd = PlayerCommand(ctx, region=region, edition=edition)
player = await cmd.player(identifier=identifier, rank=rank)   # None => already replied
if player is None:
    return
await cmd.reply(
    embed=cmd.embed(f"{player['name']}'s current points", f"The current points are **{...}**"),
    graph=cmd.graph([player], "points", borders=borders),
)
```

- `.player(...)` — defers, resolves, and on `ambiguous` shows `PlayerSelectView`
  and returns `None`; on `not_found`/`not_linked`/`too_many` replies the canonical
  message and returns `None`. The cog body never branches on `isinstance(dict)`.
- `.graph(players, kind, *, borders=None, step=False, multiple=False, params=None)`
  — returns `Graph | None` (§6.9.5).
- `.reply(embed, graph=None)` — picks `interaction.response.edit_message` when a
  callback is in flight and `ctx.followup.send` otherwise. Today each select
  callback replies through the *stale* `ctx` (`gap.py:102`, `pace.py:37`), which is
  why some cogs use `attachments=[file]` and others use `file=` by accident.
- `.embed(title, description, colour)` + `.updated_field()` convenience (§6.9.7).
- No decorator magic: explicit construction keeps the call site readable and lets
  `compare`/`compareme` (which resolve N players) drive two objects.

#### 6.9.4 One `PlayerSelectView` (bot repo, `ui.py`)

Canonicalise the two patterns that already exist and work (`when.py:12`,
`target.py:12` — `(user, players, callback)`):

```python
class PlayerSelectView(discord.ui.View):
    def __init__(self, *, author_id, players, on_select,
                 placeholder="Select the correct player...", timeout=60): ...
```

- `value=str(player["id"])` — fixes `ranking.py:75`, which uses `value=player["name"]`
  and breaks when two players share a name (and unlike list indices, an id survives
  a re-render).
- Label `#<rank>:<name>`; the name is never part of a path any more (§6.9.5), so the
  `$`-escaping mismatch between `render.py` and the 9 cogs disappears.
- Author check on every callback (`max.py` and `ranking.py` currently have none).
- `finduser` keeps a `label=name` variant of the same class rather than its own.
- **`>25` candidates never reach the view**: the resolver returns `too_many` and the
  cog replies "Too many users found… be more precise" (unchanged behaviour).
  Pagination stays a future feature, not part of this refactor.

#### 6.9.5 `GraphRenderer` / `Graph` (bot repo, `rendering.py`)

```python
@dataclass(frozen=True)
class Graph:
    path: Path
    filename: str
    def as_file(self) -> discord.File: ...

class GraphRenderer:
    def __init__(self, cache_dir: Path): ...
    def graph(self, players, kind, *, borders=None, step=False,
              multiple=False, params=None) -> Graph | None: ...
```

- `render.py` stays pure matplotlib: no `output_dir` module global, no
  `os.makedirs` at import, no `discord`.
- **Player names stop being path components.** Today `render.py:53,118,173,206`
  builds `<output_dir>/<player name>/<type>.png` and escapes `$` there, while 9 cogs
  re-derive the same path and disagree on the escape. The cache directory becomes
  `<cache_dir>/<region>/<edition>/<player id>/`, chosen by `GraphRenderer`: no
  escaping, no collisions between same-name players, and one filename rule
  (`<kind>.png`). The name stays where it belongs — in the title and the embed.
- **GIF support is deleted** (`animate`, `FuncAnimation`, `PillowWriter`). Only
  `main.py` — the abandoned tkinter UI — used it, and it is the sole reason
  `plot_and_save` cannot take a buffer later.
- `bulk_render` folds into `GraphRenderer` as `params=[...]`: it already lays several
  types out as subplots on one image (`render.py:163`), so "multiple graph types on
  the same image" is the same operation. This also deletes the `render.py:283` bug
  that passes `animate=` to `bulk_render()`, which does not accept it.
- Still writes PNGs to disk (per review); `Graph` therefore exposes `path`, and
  callers never build paths. Switching `Graph.path` to `Graph.png: bytes` with an
  LRU/TTL cache keyed by
  `(region, edition, ids, kind, border ranks, step, multiple, revision)` is the
  `TODO` follow-up and changes only `GraphRenderer`.
- Perf note: rendering is ~0.2 s and currently runs **on the event loop** with
  global `pyplot` state. Phase 1 = one `asyncio.Lock` + `asyncio.to_thread` inside
  `GraphRenderer` (cheap, correct). Phase 2, only if parallelism is ever needed =
  `Figure` + `FigureCanvasAgg` instead of `pyplot`.

#### 6.9.6 `DiscordLinkStore` (bot repo, `storage.py`)

```python
class DiscordLinkStore:
    def __init__(self, path: Path): ...
    def get(self, discord_id: int | str) -> str | None: ...
    async def set(self, discord_id: int | str, identifier: str) -> None: ...
    def all(self) -> dict[str, str]: ...
```

- 13 read sites currently re-read and re-parse the whole JSON per command.
- `link.py` does read → `await` (the Yes/No confirmation) → write on a dict that may
  be stale, and `save_discord_users` truncates before writing: a concurrent link or
  a crash loses entries. Fix: in-memory cache + `asyncio.Lock` + `tmp` +
  `os.replace`.
- Values become player **ids** (§6.8.10). No lazy resolution of the old free-text
  entries: `tools/migrate_links.py` converts them **once**, ahead of the switchover.
  It is a thin wrapper around `resolve_player` (§6.9.2) and the store, i.e. the
  first real consumer of the resolver:
  - dry-run by default, `--apply` to write; writes a timestamped `.bak` next to the
    file before replacing it (atomic, same `tmp` + `os.replace` path as `set()`);
  - needs `DATA_API_URL`/`DATA_API_TOKEN`, not the DB — the bot never opens SQLite;
  - ambiguous / not-found / too-many entries are **left untouched** and printed as a
    report (`<discord id> -> "name" (ambiguous: 2 candidates, ranks #123/#456)`), so
    the operator can fix them with `/link` rather than the script guessing;
  - idempotent: ids map to themselves, so re-running after the switchover is a no-op.
- Bot-side only: core must not know about this file.

#### 6.9.7 Response helpers (bot repo, `responses.py`)

Three small things, not a framework:

1. `updated_field(update) -> ("Updated at", "<t:…:f> (<t:…:R>)")` — one format for
   **21** copies. `update` keeps defaulting to `2005-03-30` (that stays: it is the
   easter egg and several commands do date maths on it), so the constants live here
   as `SENTINEL_UPDATE` and no cog re-invents `fromisoformat`.
2. `async def reply_error(ctx, exc, bot)` — logs and sends the "Me no worki lol ask
   Polo" message (**15** copies).
3. `REGION_CHOICES`, `BORDERS_CHOICES`, `STAT_CHOICES` + `region_autocomplete`,
   `borders_autocomplete` coroutines (**21** copies) and
   `parse_borders(value) -> list[Borders] | None` for the 8
   `find_borders(conn, 100) if borders == "1" else None` lines.

#### 6.9.8 Bugs this removes

Found while counting; all of them are deleted, not fixed in place:

- `wins.py:19` — malformed nested format spec in the select label
  (`f"#{rank:{player['name']}}"`) → `ValueError` when the menu is built.
- `ranking.py:75` — `value=player["name"]`; duplicate names select the wrong player.
- `max.py:95`, `ranking.py:63` — inline selects with no author check.
- `seed.py:155` — missing `$` escape, so the file looked up is not the file written
  (moot once player names leave the path, §6.9.5).
- `self.bot.error` does not exist (`highest.py:69`, `fetches_count.py:32`);
  `log_message` is a `NameError` in `help.py:142`. The error handler itself crashes.
- `compare.py:110`, `compareme.py:115` — `resolved_users`/`unresolved_users` live on
  the **cog singleton**, so two overlapping `/compare` calls clobber each other.
- `highest.py:50` — treats `find_player`'s result as a dict; `AttributeError` on a
  duplicate name.
- `predict.py:84` — gives up on ambiguity instead of offering the menu.
- `render.py:283` — `animate=` passed to `bulk_render()`, which has no such argument.
- Select callbacks reply via the original `ctx` instead of the `interaction`, so
  `attachments=[file]` vs `file=` differs per cog for no reason.

#### 6.9.9 Order & tests

Order (do not reorder):
1. `DataClient` exists (§6.4/§6.5) — otherwise the resolver gets written twice.
2. `Resolution` + `resolve_player` + tests (no bot changes yet).
3. `PlayerSelectView`, then convert the 13 commands one commit each, golden-diffed.
4. `GraphRenderer` (with GIF removal + `bulk` fold), then the `render()` call sites.
5. `DiscordLinkStore` (with the `/link` id + rank confirmation), then `responses.py`,
   then `tools/migrate_links.py --apply` once against `discord_users.json` while the
   bot is offline; afterwards the live file is `/data/bot/discord_users.json` and the
   tracked copy in repo A is removed with `git rm` (history untouched).
6. `compare`/`compareme` on top of the resolver (their sequential flow stays).

Tests:
- `resolve_player` with a fake backend: single, ambiguous, `not_found`,
  `not_linked`, 26 candidates → `too_many`, and the numeric-name retry.
- `build_options(players)` snapshot: escaped `$`, unicode names, equal names →
  distinct ids.
- `PlayerSelectView`: wrong user is rejected, correct user fires `on_select` once,
  and the timeout leaves a usable message.
- `GraphRenderer`: same key → same file, different `revision` → new file, `params=[…]`
  produces one multi-panel PNG, no `top100_data/` writes outside `cache_dir`.
- `DiscordLinkStore`: 10 concurrent `set()` calls all persist (today they do not).
- Golden fixtures from §6.1 for the ambiguous-name case of every converted command:
  the embed text must be unchanged.

### 6.10 Consistency
- Ingest order: commit DB → atomic metadata write with `revision+1`.
- Data service opens read-only (`file:...?mode=ro`, `uri=True`) with `busy_timeout`.
- If data service is down: web shows a friendly page (reuse `WT_Web/error.py` style),
  bot replies with a short message; no 500 traces, no long hangs (`DATA_API_TIMEOUT`).
- Never mount the SQLite file into `web`/`bot`, and never over the network. Either one
  is the signal to reconsider the boundary (it does not mean "switch to Postgres now").

### 6.11 Containers
Four images:
- `ingest` (repo A) — `requests`
- `dataservice` (repo A) — `fastapi`, `uvicorn`
- `web` (repo B) — `flask`, `requests`
- `bot` (repo C) — `discord.py`, `matplotlib`, `numpy`, `colorama` (only heavy image)

Notes:
- Split `dependencies.txt` (it lists non-pip names: `datetime`, `asyncio`,
  `sqlite3`, `tkinter`).
- `python:3.14-slim`, non-root, pinned `dokkan-core`, `PYTHONPATH=/app`,
  explicit `WORKDIR`, no `COPY . .` without `.dockerignore`.
- `.dockerignore`: `config.py.local`, `instances/`, `older_editions/`,
  `top100_data/`, `final_data/`, `*.db`, `.git`, `__pycache__/`. `WT_Archive` is never
  referenced (§3.1).
- **One compose project** on the single Docker host, compose *profiles* instead of two
  files: `data` (`ingest-glb`, `ingest-jp`, `dataservice`), `app` (`web`, `bot`),
  `admin` (one-shot admin/bootstrap). Restart policies on the long-running services;
  `dataservice` healthcheck on `/v1/health`.
- Networks: a `datanet` bridge network holding `dataservice`, `web`, `bot`, and the
  ingest containers. Only `web:2176` is published; `dataservice:8000` has **no**
  published port (the reverse proxy never sees it).
- Docker secrets for `bot_token`, `api_token`, `data_api_token` (§6.3); non-secret
  config via a plain `.env` file on the host (documented in `.env.example`).
- Bootstrap: a one-shot `bootstrap` container that builds the edition tree:
  1. every `older_editions/<REGION>/<n>/` → `data/<REGION>/<n>/`, normalising
     `<n>.db` → `database.db`, then `revision=1` on the seeded `metadata.json`;
  2. `instances/<REGION>/` → `data/<REGION>/<WT_EDITION>/` **only if** that edition is
     not already archived; otherwise log `"edition <n> already archived, instances copy
     is a leftover, skipped"`;
  3. move `discord_users.json` → `/data/bot/`.

  `instances/JP/` is empty and `older_editions/JP/` has 56–59, so `/data/JP` gets those
  and the live JP edition dir appears with the first JP fetch. The old directories stay
  untouched (no `mv`), so the bootstrap is re-runnable and idempotent.
- **The fetch upstream is external.** `<REGION>_API_BASE_URL` is a normal outbound URL
  (currently the operator's own local link; it may be another container or a remote
  host). Nothing special is needed in compose, but it must be a URL the container can
  route to — `127.0.0.1` inside a container is the container itself, so the value is
  documented per environment. `JP_API_BASE_URL` ships as a documented placeholder
  (`https://jp.invalid`) until JP's backend is fixed; JP ingest logs a clear warning and
  exits non-zero instead of fetching from a bogus host.
- Containers run as `user: "${UID}:${GID}"` so the bind-mounted `~/Dokkan/data` needs no
  `chown`.
- The Nix flake is a local devshell only: no image builds with it, and repos B/C do not
  need one.

## 7. Rollout
1. Baseline fixtures (§6.1).
2. `core` + `local` backend; migrate ingest; verify DB output identical.
3. `dataservice` + `client`; diff every endpoint against golden fixtures.
4. Point web at the client; verify pages, public API, SSE.
5. Point bot at the client; verify commands and graphs.
6. **Bot reuse layer (§6.9)**: `Resolution` + `PlayerCommand` + `PlayerSelectView`,
   then `GraphRenderer`, then `DiscordLinkStore`/`responses.py` and one run of
   `tools/migrate_links.py --apply`; one command per commit, golden-diffed, before
   touching the cog count again.
7. Split repos: `git init` in the already-created `../dokkan-web` and `../dokkan-bot`,
   add the GitHub Actions workflows (§8.1), publish the first `dokkan_core` wheel to a
   GitHub Release (tag `core-v*`), pin it in B/C, tag. Repo A is updated in place (no
   history rewrite, §3).
8. Containerize on the single Docker host behind the existing reverse proxy; bring up
   `data` first, then `app` (§6.11 profiles).
9. Move secrets to Docker secrets and rotate them, delete `config.py.local`. **Only
   now**, with the containers proven, delete root `database.db`, `instances/`,
   `older_editions/`, their `.gitignore` entries and the remaining legacy files.

## 8. CI guardrails

Every gate below is a pytest test or a plain script, so it also runs locally before a
deploy. CI is **GitHub Actions**, one workflow per repo (§8.1).

- Contract tests: `dataservice` against the golden DB, JSON equality per endpoint.
- Import isolation: web/bot must not import `sqlite3` or `dokkan_core.local`;
  ingest must not import `flask`/`discord`; nothing imports `cogs.utils`.
- Import isolation for the wrappers: `dokkan_core` imports neither `discord` nor
  `flask`; `render.py` imports neither `discord` nor `os.path` for output dirs;
  `render(`, `bulk_render(` and `discord.ui.Select` appear only in `rendering.py`
  and `ui.py` respectively.
- Grep gate: no `../instances`, `../older_editions`, `top100_data`, `database.db`
  literals outside `core/paths.py`.
- Duplication gate (§6.9): at most one occurrence each of `"Multiple players found"`,
  `"You did not provide a Dokkan"`, `"Me no worki"`, `"2005-03-30"`,
  `"Updated at"`, and `replace("$"` outside `responses.py`/`rendering.py`.
- `docker build` for all four images + dataservice healthcheck smoke test.
- Optional leaderboard query benchmark on a 10k-player DB (it full-scans JSON text).

### 8.1 GitHub Actions (one workflow per repo)

| Repo | Trigger | Jobs |
|---|---|---|
| A `dokkan-data` (private) | push; tag `core-v*` | `pytest` (core + dataservice contract against the fixture DB), grep/import gates, `docker build` for `ingest` + `dataservice`; on tag: `python -m build` and attach `dokkan_core-*.whl` to the GitHub Release |
| B `dokkan-web` | push, PR | `pytest` (route/JSON fixtures), grep gates, `docker build` |
| C `dokkan-bot` | push, PR | `pytest` (resolver, views, rendering, store — no Discord), grep gates, `docker build` |

- B/C install `dokkan_core` from repo A's release asset; the download token is the
  `CORE_WHEEL_TOKEN` repo secret, so no SSH keys and no private index are needed.
- CI secrets are GitHub secrets; runtime secrets are Docker secrets. Neither ever lives
  in a repo, and `config.py.local` is not committed (§6.3).
- The `docker build` job is a smoke test; deployment stays manual (`git pull` + compose
  on the machine) until a CD step exists.

## 9. Risks
- **Chattiness**: current web code does N+1 player lookups. Bulk endpoints
  (`/top100`, `/bulk`) are mandatory before moving the DB off-host.
- **Latency**: web/bot now depend on a hop over the compose network. `DATA_API_TIMEOUT`
  and caching are required, not optional.
- **Auth**: the data service is read-only and has no published port, so it is reachable
  only from `datanet`. The bearer token is defence in depth, not the only barrier.
- **Secrets**: `config.py.local` has real tokens on disk; rotate them.
- **Backwards compatibility**: external consumers of `/api/get-top100`,
  `/api/get-user`, `/api/<n>/metadata` (if any) must keep their shapes.
- **SQLite concurrency**: WAL + single writer is fine; multiple writers are not.
- **Refactor sequencing**: the §6.9 wrappers must land **after** `DataClient` and
  **before** the per-command edits. Doing it the other way round means rewriting the
  same 13 preludes twice. Converting commands one at a time keeps every step
  revertable while the bot stays shippable.
- **Behaviour drift**: `Resolution` deliberately changes `find_player`'s
  dict-or-list contract. `compare`/`compareme`/`bulk` keyed results by player *name*,
  so two same-name players collapsed into one entry; keying by id is a fix, but it
  changes which lines appear on the `multiple*.png` graph — check the golden fixture
  for the duplicate-name case.

## 10. Definition of done
- [ ] `grep` for cross-imports between ingest/web/bot returns nothing.
- [ ] Web and bot images contain no `sqlite3` usage.
- [ ] Ingest writes only atomically; data service opens read-only.
- [ ] `/v1/status` `revision` changes within one poll interval of a new fetch.
- [ ] Golden fixtures match for web routes and bot command outputs.
- [ ] Each service starts and works with the other two stopped.
- [ ] `docker compose --profile data --profile app up` reaches a working leaderboard on
      this machine, behind the existing reverse proxy, with all secrets from
      `/run/secrets` and no `.env` token.
- [ ] `~/Dokkan/data` is the only data location, laid out `<REGION>/<edition>/`; no code
      references `~/Dokkan/instances`, `~/Dokkan/older_editions` or `WT_Archive`.
- [ ] Root `database.db`, `instances/` and `older_editions/` are deleted only after the
      containers have been proven (§7.9).
- [ ] JP works end to end with an empty `data/JP` (ingest creates it on first run).
- [ ] Ingest refuses to write into an archived edition dir (no `fetches/`, has
      `first.json`) and says to bump `<REGION>_WT_EDITION`.
- [ ] §6.9 wrappers exist and are the only implementations: one `resolve_player`,
      one `PlayerSelectView`, one `GraphRenderer`, one `DiscordLinkStore`,
      one `updated_field`/`reply_error`.
- [ ] Every player-taking command shows the same selection menu on a duplicate name
      (including `/predict`, `/highest`, `/link`) and the same rank/id label.
- [ ] `discord_users.json` writes are atomic and the concurrency test passes.
- [ ] `tools/migrate_links.py --apply` has run; its report lists only entries that
      genuinely need a human (ambiguous/not-found names).
- [ ] No GIF code path remains in `render.py`.

## 11. Review decisions (§6.9)

Resolved during review; recorded so they are not re-litigated:

| Question | Decision |
|---|---|
| Resolver failure signalling | Tagged `Resolution(kind=...)` return value, no exceptions |
| Command ergonomics | Explicit `cmd = PlayerCommand(ctx, region=…); await cmd.player(...)`, no decorator |
| `>25` candidates | Keep the "too many users, be more precise" reply; no pagination |
| Select option values | `player["id"]`, never list indices or names |
| `/link` | Disambiguate first, showing `#rank name` **and** the player id (region defaults to GLB like every other command); store the **player id** |
| `/predict`, `/highest` | Adopt the selection menu; audit all other commands for the same |
| Renderer output | Keep writing PNG files for now; `BytesIO`/LRU stays the `TODO` follow-up |
| GIF/`animate` support | Deleted |
| `2005-03-30` fallback | Kept — it is the easter egg, not dead code |
| `bulk` rendering | Folded into `GraphRenderer(params=[...])`, since multi-type on one image already exists |
| Graph cache layout | `<cache>/<region>/<edition>/<player id>/<kind>.png` — ids, never names, so no `$` escaping and no same-name collisions |
| `/link` migration | One-shot `tools/migrate_links.py --apply`; no lazy resolution, untouched entries get a report |
| `PlayerRef`/`Resolution` home | `dokkan_core`, so the web's `/search_player` can reuse them later |

## 12. Questions raised during review

All questions from the review rounds are answered. §12.1 is the record so they are not
re-litigated; §12.2 lists the small choices made without asking. No open question blocks
starting the work.

### 12.1 Answered

| Question | Decision |
|---|---|
| Hardcoded data paths | Removed. One host root `~/Dokkan/data` bind-mounted at `/data`, laid out `<REGION>/<edition>/` |
| `~/Dokkan` vs `~/Dokkan/dokkan-data` | `~/Dokkan` is now only the parent of the three repos; the old `~/Dokkan/instances` paths in `config.py` are stale and must not be reused |
| Repo count | **3** — `core/` lives in repo A |
| Repo A | The existing `DokkanWTBot` repo, updated in place — no history rewrite, no `filter-repo` |
| Repos B/C | The already-created empty dirs, fresh `git init` when their code lands |
| Core distribution | Wheel published to a GitHub Release of repo A, pinned in B/C |
| CI | GitHub Actions, one workflow per repo (§8.1) |
| Hosts | All containers on one Docker instance on one machine; existing reverse proxy |
| Container networking | Only the containers need to talk to each other (`datanet`); no published `dataservice` port |
| Fetch upstream | External. May be another docker link or a remote host; only `<REGION>_API_BASE_URL` matters |
| JP upstream | Documented placeholder (`https://jp.invalid`) until the backend is fixed |
| JP data | Keep full support even though it currently has none (`data/JP` starts empty) |
| Region routing | Both `?region=` and the hostnames `dokkan-wt.info` (GLB) / `jpn.dokkan-wt.info` (JP) |
| Current edition | Manual `<REGION>_WT_EDITION`, bumped by hand |
| Secrets | Docker secrets at runtime, GitHub secrets in CI |
| Backups | None automated — raw fetches archived by hand in `../WT_Archive/RawData` can rebuild every DB |
| `~/Dokkan/WT_Archive` | Unrelated to the refactor; never read, moved, or referenced (§3.1) |
| Stale root `database.db`, `instances/`, `older_editions/` | Kept until the containers are proven; deleted at §7.9 |
| Database filename | Always `database.db`, current and archived; `<edition>.db` is normalised away |
| Edition numbers | Per region — `GLB/55` and `JP/55` coexist and are unrelated |
| Archived edition contents | `database.db` + `metadata.json` + `first.json` + `latest.json`; no `fetches/` |
| Archived editions are immutable | Ingest refuses to write into one; bump `<REGION>_WT_EDITION` instead |
| Edition 63 leftover in `instances/` | Archive wins; leftover skipped by bootstrap, deleted at §7.9 |
| `discord_users.json` | Migrated to `/data/bot/discord_users.json`, then **untracked** (history left alone) |
| Link migration timing | Run while the bot is offline / during a maintenance window |
| `predict` | Server returns the numbers only; the bot composes the embed |
| Tests | Per repo, own features only; no Discord connection in bot tests |
| Nix | Local devshell only, trimmed |
| Container user | `user: "${UID}:${GID}"` |
| `create_edition_fetches.py` | Moves to `ingest/admin/` |
| Legacy scripts | `test_time_*`, `manual_update*`, `final_render` stay as `admin` entrypoints, even if unused |
| `/api/*` compatibility | External consumers exist → routes stay byte-identical |

### 12.2 Decided without asking (flag if wrong)

- **Wheel hosting**: GitHub Releases on repo A (`core-v*` tags), downloaded in B/C CI and
  image builds with a `CORE_WHEEL_TOKEN` secret. A private PyPI can replace it later by
  changing the index URL only; for an offline build, a parent-dir build context
  (`docker build -f dokkan-bot/Dockerfile ~/Dokkan`) stays the fallback.
- **Pin style**: `dokkan-core~=X.Y` in B/C (no `==`, no git URLs).
- **JP placeholder**: `https://jp.invalid` — a reserved TLD, so a misconfigured JP fetch
  fails fast and visibly instead of hitting a real host.
- **Flake trim**: drop the DearPyGui derivation (only the abandoned `main.py` needs it),
  frida/`frida-tools`, `peewee`, `ics`, `tkinter`; keep `python314`, `matplotlib`,
  `requests`, `discord.py`, `flask`, `fastapi`, `uvicorn`, `docker`.
- **`.env.example`** is committed in each repo; the real `.env` is not.
- **`GET /v1/status` is the only polled endpoint** for SSE (cheap, revision-based); web
  and bot both use it, so `DATA_API_TIMEOUT` defaults to 5 s and one retry.

### 12.3 Edition 63 duplicate — resolved

`older_editions/GLB/63/` is a finished edition that was never removed from `instances/`.
Confirmed by you: 63 is an **older edition**, and `instances/GLB/` is the leftover you
forgot to clean up when archiving. Consequences baked into §5/§6.11:

- The archive copy of 63 wins; the `instances/GLB/` copy (211 MB DB + 956 MB of fetches,
  290 files) is skipped by the bootstrap and deleted at §7.9.
- The two DBs are not byte-identical (same row counts, different SHA-256), which is why
  "merge the two" is explicitly forbidden.
- Nothing is lost: edition 63's data survives in `older_editions/GLB/63/`, and the raw
  fetches live on in `../WT_Archive/RawData` (manual archive, §3.1).
- Consequence for ingest: while `<REGION>_WT_EDITION` still says 63, GLB ingest must
  refuse to run (archived dir is immutable) until you bump it to the new edition.
