# 🎮 PlayLog — Self-Hosted Game Library Server

PlayLog consolidates a personal game collection from multiple storefronts into one
dashboard: owned titles, playtime, and a backlog, enriched with metadata and cover
art from [IGDB](https://www.igdb.com/). It is a single-user, single-container web app
built for a small home server (e.g. OpenMediaVault) and is meant to be reachable only
inside your private **Tailscale tailnet**.

- **Backend:** Python 3.12 + FastAPI, SQLite via SQLAlchemy (async), APScheduler in-process
- **Frontend:** React + Vite + TypeScript, built to static files and served by FastAPI
- **Delivery:** one Docker container, one exposed port (`8787` by default)

```
┌────────────┐   tailnet    ┌───────────────────────────────┐
│  browser   │ ───────────▶ │  playlog container :8787      │
│ (phone/PC) │              │  ├─ FastAPI (API + SPA)       │
└────────────┘              │  ├─ APScheduler (Steam sync)  │
                            │  └─ /data volume ─┬─ playlog.db (SQLite)
                            │                    └─ covers/  (cached art)
                            └───────────────────────────────┘
                                     ▲ Steam Web API / IGDB (outbound HTTPS)
```

## Repository layout

```
├── backend/            FastAPI application
│   ├── app/
│   │   ├── main.py         app factory + SPA static serving
│   │   ├── config.py       env-driven settings
│   │   ├── database.py     async engine/session, UTC datetime type
│   │   ├── models/         games, storefronts, ownerships, play_sessions, sync_status, auth
│   │   ├── schemas/        Pydantic request/response models
│   │   ├── routers/        auth, games, sync, igdb, library (recently-played)
│   │   ├── services/       StorefrontAdapter interface, Steam adapter, IGDB client,
│   │   │                   matching, sync orchestration, cover cache, library queries
│   │   ├── auth/           password hashing (bcrypt) + JWT sessions
│   │   └── scheduler/      APScheduler jobs
│   └── tests/              pytest suite (unit + API integration, mocked Steam/IGDB)
├── frontend/           Vite + React + TypeScript SPA
├── data/               runtime volume (SQLite file + covers/), bind-mounted
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

## Quick start (Docker, on the OMV host)

```bash
git clone <this-repo> && cd PlayLog
cp .env.example .env
$EDITOR .env        # set APP_PASSWORD, and Steam/IGDB credentials if you want sync
mkdir -p data/covers
docker compose up --build -d
```

Open `http://<omv-tailscale-ip>:8787` (see *Tailscale* below) and log in with
`APP_PASSWORD`.

Verify the data survives a restart (it lives in `./data`):

```bash
docker compose down && docker compose up -d   # library, covers and settings persist
```

## Environment variables

All configuration comes from the environment (a `.env` file next to
`docker-compose.yml` is loaded automatically). See `.env.example`.

| Variable | Required | Default | Description |
|---|---|---|---|
| `APP_PASSWORD` | **yes** | — | Single application password. Only a salted bcrypt hash is stored in the DB. Changing it + restart rotates the password. |
| `PORT` | no | `8787` | The single HTTP port the app listens on and publishes. |
| `SESSION_TTL_HOURS` | no | `24` | Login session lifetime. |
| `SYNC_INTERVAL_HOURS` | no | `12` | How often the Steam library is synced (also runs once at startup). |
| `STEAM_API_KEY` | for Steam sync | — | Steam Web API key. |
| `STEAM_ID64` | for Steam sync | — | Your 64-bit Steam ID. |
| `IGDB_CLIENT_ID` | for IGDB enrichment | — | Twitch dev app client ID (used for IGDB). |
| `IGDB_CLIENT_SECRET` | for IGDB enrichment | — | Twitch dev app client secret. |
| `STEAMGRIDDB_API_KEY` | for SteamGridDB art | — | Bearer key for the SteamGridDB API v2. |

`DATA_DIR` (default `/data` in the container) is where `playlog.db` and `covers/`
live — always the bind-mounted volume, so existing OMV backup jobs cover them.

### Getting a Steam API key

1. Go to <https://steamcommunity.com/dev/apikey>, log in, enter any domain name
   (e.g. `localhost`) and register → copy the key into `STEAM_API_KEY`.
2. Find your SteamID64 via <https://steamid.io> (look up your profile) → `STEAM_ID64`.

### ⚠️ Steam profile privacy requirement

The owned-games and recently-played endpoints only work when the profile's
**Game Details are Public**: on Steam → *Edit Profile → Privacy Settings →
"Game Details" → **Public**. If the profile is private, Steam returns an empty
response and PlayLog records a visible sync error (it never crashes).

### Getting IGDB credentials

1. Log in at <https://dev.twitch.tv/console/apps> and create an application.
2. Copy the **Client ID** and generate a **Client Secret**.
3. Put them in `IGDB_CLIENT_ID` / `IGDB_CLIENT_SECRET`.

PlayLog uses the OAuth *client credentials* flow automatically and caches the token
in memory. IGDB is used for cover art, description, genres and release year, and to
match Steam app IDs to IGDB games via the `external_games` endpoint (falling back to
title search). If IGDB is not configured, everything still works — games are just
added without metadata, and covers can be enriched later.

### SteamGridDB — cover art, icons and logos

Set `STEAMGRIDDB_API_KEY` (get a Bearer key at
<https://www.steamgriddb.com/profile/preferences/api>) to additionally fetch, per
game:

- **cover grid** (prefers 600×900) → cached and served at `GET /api/games/{id}/cover`
- **icon** → `GET /api/games/{id}/icon` (shown as a small overlay on library cards)
- **logo** → `GET /api/games/{id}/logo` (shown on the game detail page)

Behaviour:

- During Steam sync and when adding a game manually, missing assets are fetched
  automatically (matched by Steam appid when known, otherwise by title search).

Genres come from IGDB when available; when IGDB has none for a synced Steam game,
they are filled from Steam's keyless public store API
(`store.steampowered.com/api/appdetails?filters=genres`, one request per game,
best-effort — rate-limited or failing responses just leave genres empty).
- On the game detail page, **"Fetch art from SteamGridDB"** re-downloads all three
  (`POST /api/games/{id}/assets/refresh`), overwriting the cached files.
- Files are stored once in `data/covers/` as `sgdb_grid_*.png`, `sgdb_icon_*`,
  `sgdb_logo_*` and served locally afterwards — remote images are never proxied.
- SteamGridDB failures are best-effort: they are logged, never fail a sync, and the
  game simply keeps its existing art. Mind the free-tier rate limits of your API key;
  the automatic fetch only runs for games that are missing assets.

### Tailscale

PlayLog has no public exposure by design. Recommended setup on OMV:

- Keep the container on the default bridge network and publish the port only on the
  host's Tailscale IP, e.g. in `docker-compose.yml`:
  `ports: - "100.x.y.z:${PORT:-8787}:${PORT:-8787}"` (replace with your OMV host's
  tailnet address), or
- Use Tailscale Serve/Funnel to expose the container, or rely on tailnet ACLs to
  restrict who can reach port 8787.

The session cookie is `HttpOnly` + `SameSite=Lax` and served over plain HTTP, which
is fine on a private tailnet.

## Using the app

1. **Log in** with `APP_PASSWORD` (first start hashes and stores it in the DB).
2. **Dashboard** (`/`): cover grid with storefront badges and playtime, text search,
   filters (storefront / backlog status / tag), a *recently played* strip, and a
   *Sync Steam* button with per-storefront status.
3. **Add game** (`/add`): type a title → IGDB dropdown with covers → pick a match to
   auto-fill metadata, or add a manual entry (DRM-free/retro). Manual entries get a
   `manual` ownership and support manually logged play sessions.
4. **Game detail** (`/games/{id}`): description, genres, release year, backlog
   status, rating (0–10), tags, notes, ownership list, play sessions (add manual
   ones there).
5. **Sync**: Steam syncs automatically every `SYNC_INTERVAL_HOURS` and once at
   startup; trigger it manually from the header. Steam playtime is authoritative for
   synced titles. The last sync result per storefront is always visible
   (`GET /api/sync/status`), including errors.

## API overview

All `/api/*` routes except `POST /api/auth/login` require a session (cookie or
`Authorization: Bearer <token>`).

| Method & path | Description |
|---|---|
| `GET /api/health` | public liveness probe (container healthcheck; no auth) |
| `POST /api/auth/login` | `{password}` → session token (also set as cookie) |
| `POST /api/auth/logout`, `GET /api/auth/me` | session management |
| `GET /api/games?search=&storefront=&status=&tag=&genre=&sort=` | list games with aggregates; `genre` matches one entry of the comma-separated genre list exactly (case-insensitive, no substring false positives); `sort` = `title`, `title_desc`, `playtime`, `playtime_asc`, `recent`, `year`, `year_asc`, `genre`, `genre_desc` (default `title`) |
| `POST /api/games` | manual entry, optionally `{igdb_id}` for IGDB enrichment |
| `GET/PATCH /api/games/{id}` | read / update status, notes, rating, tags, title |
| `GET /api/games/{id}/cover` | locally cached cover image (IGDB or SteamGridDB) |
| `GET /api/games/{id}/icon`, `GET /api/games/{id}/logo` | locally cached SteamGridDB icon / logo |
| `POST /api/games/{id}/assets/refresh` | re-fetch cover/icon/logo from SteamGridDB |
| `PUT /api/games/{id}/assets/{kind}` | upload a custom `cover`/`icon`/`logo` (raw image body, ≤10 MB) |
| `DELETE /api/games/{id}/assets/{kind}` | clear a cached asset |

`PATCH /api/games/{id}` also accepts `title`, so titles can be edited manually from
the game detail page (the "Artwork" panel there handles uploads/clears).
| `GET /api/meta` | which integrations are configured (steam / igdb / steamgriddb) |
| `GET/POST /api/games/{id}/sessions` | play sessions (manual logging) |
| `GET /api/igdb/search?q=` | IGDB title search for the add-game picker |
| `GET /api/sync/status` | last sync result per storefront |
| `POST /api/sync/steam` | trigger a Steam sync now |
| `GET /api/recently-played` | recently played strip data |

The built SPA is served at `/` with a catch-all fallback for client-side routes.

## Data model

- **games**: id, title, igdb_id (nullable), description, cover_filename, release_year,
  genres, status (`unplayed|in_progress|completed|abandoned`), notes, rating (0–10),
  tags (comma-separated), created_at
- **storefronts**: id, name (`steam|epic|gog|manual`), external_user_id (nullable)
- **ownerships**: id, game_id, storefront_id, store_product_id (nullable), acquired_at,
  last_synced_at (+ playtime_minutes / last_played_at / recent_playtime_minutes from
  the storefront — Steam playtime is authoritative)
- **play_sessions**: id, game_id, started_at, ended_at, source (`steam|manual`)
- **sync_status**: per-storefront last run (time, success, error, items)
- **auth_config**: salted bcrypt hash of `APP_PASSWORD` only — no other secrets are
  ever stored in the database

Epic Games Store and GOG are deliberately not implemented yet; the
`StorefrontAdapter` interface (`backend/app/services/storefront_base.py`) is ready so
new adapters can be dropped in without refactoring the sync pipeline.

## Development

Backend (needs Python 3.12 + pip):

```bash
cd backend
pip install -r requirements.txt
APP_PASSWORD=dev pytest            # run the test suite (mocked Steam/IGDB)
APP_PASSWORD=dev uvicorn app.main:app --port 8787   # API only
```

Frontend:

```bash
cd frontend
npm install
npm run dev        # Vite dev server on :5173, proxies /api → localhost:8787
npm run build      # production build into frontend/dist (served by FastAPI)
```

## Tests

```bash
cd backend && pytest
```

The suite covers the pure matching logic, Steam payload parsing, the sync pipeline
(upserts, playtime deltas → sessions, failure recording, dedup against manual
entries), and API integration tests (auth, CRUD, cover serving, mocked Steam sync +
mocked IGDB via dependency overrides and `httpx.MockTransport`, persistence across
"restarts").

## Backup

Everything that matters lives in the bind-mounted `./data/` directory
(`playlog.db` + `covers/`). Point your existing OMV backup job at that folder — no
database service to dump, no external state. The database runs in WAL mode with a
60 s busy timeout, and syncs are serialized in-process, so the scheduled sync and
manual actions (sync button, art refresh, edits) can safely overlap.
