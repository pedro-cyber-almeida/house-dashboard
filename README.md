# House Dashboard

A small, self-hosted dashboard for your services, with real server-side health
checks — no browser-only fetches, no JavaScript-only state. One container, one
SQLite database, zero external services.

- **Real health states** — every card shows `online` / `offline` / `degraded` /
  `unknown`, decided *by the server* (it probes the service's well-known health
  paths: `/health`, `/healthz`, `/ping`, `/api/health`, `/api/ping`, `/`), so
  the status is not subject to browser CORS or DNS.
- **Any service, now or in the future** — the catalogue is a plain
  name + `http(s)://` URL list managed in the admin UI. Add services that
  don't exist yet; they simply read `unknown` (unresolvable) or `offline`
  until they're up.
- **Per-user dashboards** — admins curate the global catalogue; each user only
  sees the services assigned to them, in an order they can set themselves with
  up/down buttons (grouped by free-form category).
- **Search** — instant name/description filter per user's dashboard.
- **Accounts & sessions** — bcrypt passwords, signed session cookie
  (`samesite=lax`, `secure` in production), two roles: `admin` and `user`.
- **Logos** — PNG/JPEG/SVG upload *and* a one-click "Fetch icon" that grabs
  the service's own favicon (validated by magic bytes, 512 KB cap); icons
  render via `data:` URLs only.
- **Smart categories** — a category is suggested automatically from the
  service name (Sonarr → Media, Pi-hole → Network, Ollama → AI, …); always
  overridable, groups render A-Z on the dashboard.
- **Configurable identity** — set your own app name with `DASH_APP_NAME`.
- **Installable PWA** — a web app manifest (name follows `DASH_APP_NAME`)
  plus a minimal service worker that caches the shell, so the dashboard can
  be added to a home screen and its frame opens offline. Health states are
  never served from cache (the worker bypasses `/api/` and all probes stay
  live).
- **Vanilla-JS front-end**, dark/light/system theme per account.

## Quick start (Docker)

```sh
git clone <repo-url> house-dashboard
cd house-dashboard
cp .env.example .env
# edit .env: set DASH_ADMIN_PASSWORD (required) — everything else has defaults
docker compose up -d --build
```

Open `http://localhost:8090` (the default host-side port; see `DASH_BIND`
below), log in with `admin` / the password you set, then:

1. **Services** (admin screen): create services — any name, any
   `http(s)://` URL, optional description/category/logo.
2. **Users**: create accounts, assign services to each one.
3. Users log in on the normal dashboard and reorder their tiles (↑/↓ on
   hover) inside each category.

State lives in the `dashboard_data` Docker volume (`/data` — SQLite database
plus the generated session key). Back it up by backing that volume up.

## Configuration

All configuration is environment variables (no config file). Copy
`.env.example` to `.env` — the only **required** value is
`DASH_ADMIN_PASSWORD` (used for the first admin account on the very first
startup; it's ignored afterwards).

| Variable | Default | Meaning |
| --- | --- | --- |
| `DASH_APP_NAME` | `House Dashboard` | Display name (top bar, login screen, browser tab). |
| `DASH_ADMIN_USERNAME` / `DASH_ADMIN_PASSWORD` | `admin` / — | Bootstrap of the first admin (first run only). |
| `DASH_BIND` | `127.0.0.1:8090` | Host-side bind for the container port (`host:port:8000` left side). The container always listens on 8000. |
| `DASH_HOST` / `DASH_PORT` | `127.0.0.1` / `8000` | Bind for non-Docker runs. |
| `DASH_DATA_DIR` | `./data` (Docker: `/data`) | Where the SQLite DB and `.secret` live. |
| `DASH_DB_PATH` | `$DASH_DATA_DIR/dashboard.db` | Direct DB path override. |
| `DASH_SECRET_KEY` | auto-generated in `.secret` | Session cookie signing key (generated and persisted if omitted). |
| `DASH_COOKIE_SECURE` | auto (off on localhost, on otherwise) | Force `true` behind HTTPS. The compose file sets it to `true`. |
| `DASH_COOKIE_MAX_AGE` | `43200` | Session lifetime, seconds. |
| `DASH_PROBE_TIMEOUT` | `3.0` | Health-probe timeout, seconds. |
| `DASH_PROBE_CACHE_TTL` | `30` | How long a probe result is cached per URL. |

> The compose file binds loopback by default on purpose: point a TLS
> reverse proxy (Caddy, Nginx, Traefik…) at `127.0.0.1:8090` and you're
> exposed safely. Only change `DASH_BIND` to a non-loopback address if you
> know why.

## Health states

| State | Meaning |
| --- | --- |
| `online` (green) | A known health path answered 2xx/3xx. |
| `degraded` (amber) | The TCP/HTTP endpoint answers, but none of the health paths confirms. |
| `offline` (red) | Connection refused / timeout. |
| `unknown` (grey) | The hostname doesn't resolve from the server — also the state of a service you created **before it exists yet**. |

Results are cached per URL for `DASH_PROBE_CACHE_TTL` seconds and probes are
concurrency-capped, so a page load never hammers your services.

## Service logos

Each service accepts a logo uploaded manually (PNG, JPEG or SVG, ≤ 512 KB).
Alternatively, in the admin screen → **Services**, the **Fetch icon** button
downloads the favicon from the service itself (it scans `<link rel="icon">`
on the home page, then falls back to `/favicon.ico`) and stores it with the
same magic-byte validation as uploads. Note: this only works while the service
is online and only for PNG/JPEG/SVG favicons — services without a favicon keep
their initials placeholder.

## Development (no Docker)

```sh
uv sync --dev
export DASH_ADMIN_USERNAME=admin DASH_ADMIN_PASSWORD=dev-password-123
uv run uvicorn dashboard.main:app --reload
```

Checks: `uv run ruff check . && uv run ruff format --check .`

## Repository layout

```
src/dashboard/
  main.py            # app factory, middleware (CSP, HSTS, sessions)
  config.py          # env-driven settings
  database.py        # SQLite engine + additive migrations
  seed.py            # first-admin bootstrap (idempotent)
  models.py          # SQLModel: User, Service, UserServices
  schemas.py         # pydantic request/response
  security.py        # bcrypt hashing
  auth/              # session login/logout + role dependency
  api/
    services.py      # /api/services/* (assigned list, order, probes)
    me.py            # profile, theme, avatar, password change
    admin/           # users, services catalogue, logo upload
  static/            # vanilla-JS front-end (no build step); sw.js PWA shell
  scripts/
    make_pwa_icons.py  # regenerates static/icons/icon-*.png (stdlib only)
```
