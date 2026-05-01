# Deploying AOE via the Arango Container Manager (Manual Packaging)

**Audience:** operators deploying AOE alongside an existing ArangoDB cluster
using the **Arango Container Manager** with **manual packaging**
(`.tar.gz` + the `py13base` image / `uv`) — **not** the unified Docker image
path documented in [`arango-cloud-deployment.md`](./arango-cloud-deployment.md).

> Looking for the Docker / `docker save` route? See
> [`arango-cloud-deployment.md`](./arango-cloud-deployment.md). The two paths
> are mutually exclusive — pick one per environment.

---

## 1. When to use this path

| You should use this path when… | You should use the Docker path when… |
|--------------------------------|--------------------------------------|
| Your platform integrates the Arango Container Manager and offers `py13base` for Python services | You are running outside the Arango platform on a vanilla container host |
| You want operations to mirror how Arango itself ships services (manual packaging) | You want a single OCI image that bundles nginx + Next + Python |
| You don't want to maintain an OCI registry or use `docker save` workflows | You already have an image registry and CI for `docker build` / `push` |
| You want to ship a `.env` alongside the bundle for first-bring-up | You manage env exclusively from the platform UI |

The output of this path is a **single tarball** (`aoe-myservice.tar.gz`)
containing the FastAPI app, migrations, `pyproject.toml` / `uv.lock`, an
entrypoint shim, optionally a Next.js static export, and optionally `.env`.

---

## 2. Architecture at a glance

```
┌────────────────────────────────────────────────────────────────────┐
│  Arango Container Manager pod (py13base + uv)                       │
│                                                                    │
│   ./entrypoint   (Python; line 1: `entrypoint = __file__`)          │
│      │                                                             │
│      ├─ uv pip install -e .   (deps from pyproject.toml + uv.lock) │
│      ├─ exec migrations  (alembic-style; reads ARANGO_ENDPOINT)    │
│      └─ exec uvicorn app.main:app                                  │
│                                                                    │
│   FastAPI app                                                      │
│      ├─ StripServicePrefixMiddleware  (peels SERVICE_URL_PATH_PREFIX) │
│      ├─ /api/v1/...   business routes                              │
│      ├─ /ws/...       WebSocket routes                             │
│      └─ /             NextStaticExportApp(frontend/out/<prefix>/)  │
│                          (only if PACKAGE_INCLUDE_FRONTEND=1)      │
└──────────────────┬─────────────────────────────────────────────────┘
                   │ python-arango → ARANGO_ENDPOINT
                   ▼
       ┌─────────────────────────────┐
       │   ArangoDB cluster (remote) │
       └─────────────────────────────┘
```

The DB runs **outside** the app pod — the cluster URL must come from `.env`
or platform-set env vars (never hard-coded).

---

## 3. Build commands

```bash
# Backend-only — fastest, no Node required, no UI in tarball
make package-arango-manual

# Backend + Next.js static export bundled at frontend/out/<prefix>/
# Requires SERVICE_URL_PATH_PREFIX in .env (Makefile reads via include)
make package-arango-manual-all
```

Both write to the repo-root: **`aoe-myservice.tar.gz`**.

What the script does (`scripts/package-arango-manual.sh`):

1. Stages `backend/{app,migrations,pyproject.toml,uv.lock,entrypoint}` into
   a flat archive tree.
2. Copies repo-root `.env` into the bundle if present (skip by removing it
   first).
3. If `PACKAGE_INCLUDE_FRONTEND=1`:
   - Validates `SERVICE_URL_PATH_PREFIX` is set (no trailing slash).
   - Runs `npm ci` (or `npm install`) in `frontend/`.
   - Runs `AOE_STATIC_EXPORT=1 npm run build` with the prefix in env.
   - Copies `frontend/out` into the bundle at `frontend/out/`.
4. On macOS strips Apple-specific extended attributes
   (`COPYFILE_DISABLE=1` + `xattr -cr`) so Linux extractors don't choke on
   PAX header warnings.
5. Produces `tar -czf aoe-myservice.tar.gz` — **flat layout** (entrypoint at
   archive root). Override with `PACKAGE_USE_TOPDIR=1` for nested
   `myservice/…` layout.

### Resulting tar layout (flat, default)

```
aoe-myservice.tar.gz
├── entrypoint          ← Python, line 1 starts with `entrypoint`
├── pyproject.toml
├── uv.lock
├── .env                ← optional; copied if repo-root .env exists
├── app/
│   ├── main.py
│   ├── config.py
│   ├── api/
│   ├── db/
│   ├── extraction/
│   └── …
├── migrations/
│   └── NNN_*.py
└── frontend/           ← only with PACKAGE_INCLUDE_FRONTEND=1
    └── out/
        ├── _next/
        ├── library.html
        ├── workspace.html
        ├── ontology/
        │   └── edit.html
        └── <prefix>/
            └── index.html
```

---

## 4. Container Manager quirks (read this before debugging)

These are platform-specific behaviours of the Arango Container Manager that
shaped how the entrypoint, packaging script, and config are written. Each one
is encoded as a defensive check somewhere in the codebase — don't undo them
without re-validating against the platform.

### 4.1 Entry script detection

The platform effectively runs `python /project/<token>` where `<token>` is
the **first whitespace-separated word** of the file named `entrypoint`.

**Therefore:** line 1 of `backend/entrypoint` must start with the literal
text `entrypoint`. The actual code is:

```python
entrypoint = __file__   # ← line 1, MUST be exactly this token
import os
import shutil
import subprocess
import sys
from pathlib import Path
…
```

A leading `"""docstring"""`, `# shebang`, `from x import y`, or even a
comment will break entrypoint detection — the platform will try to
`python /project/"""` (or whatever the first token resolves to) and fail.

### 4.2 Tar layout

Archives must be **flat** — `entrypoint` at the tar root — not nested under
`myservice/entrypoint`. The packaging script defaults to flat; set
`PACKAGE_USE_TOPDIR=1` for the nested layout if your platform needs it.

### 4.3 macOS xattrs leaking into PAX headers

macOS adds Apple-specific metadata as extended attributes
(`com.apple.provenance`, `com.apple.quarantine`). When `tar` includes them,
some Linux extractors warn or fail with `stream closed: EOF`. The script
mitigates by:

```bash
export COPYFILE_DISABLE=1     # before any cp / tar
xattr -cr "${STAGE}/${NAME}"  # before tar (Darwin only)
```

If you build on Linux, both calls are no-ops.

### 4.4 Dependencies without `pip` in the venv

`py13base` venvs sometimes have **no `pip` module**. The entrypoint prefers
`uv pip install -e . --python sys.executable` because `uv` installs without
needing `pip` first. Fallback: `python -m ensurepip` then `pip install -e .`.

`_find_uv()` in `backend/entrypoint` looks for `uv` in this order:

1. `UV_BINARY` env var (if set and executable)
2. `shutil.which("uv")` — i.e. `PATH`
3. Hard-coded fallbacks: `/usr/local/bin/uv`, `/usr/bin/uv`,
   `~/.local/bin/uv`, `~/.cargo/bin/uv`

`AOE_SKIP_UV_SYNC=1` skips the install step entirely (useful if your image
already pre-installs deps).

### 4.5 `.env` path and current working directory

The platform sets `cwd=/project`. An old `env_file: "../.env"` in `Settings`
resolved to `/.env` and silently failed to load anything.

**Current behaviour:** `backend/app/config.py` uses `_resolved_env_files()`
which derives candidate paths from `Path(__file__)` — picking up:

- `…/<repo>/.env` (repo-root, monorepo dev)
- `…/project/.env` (sibling of `app/` in the manual-packaging bundle)

Whichever exists wins; both is fine (later overrides earlier). The packaging
script copies `${REPO_ROOT}/.env` into the bundle so this just works on
first bring-up.

### 4.6 Loopback guard

The entrypoint imports `from app.config import settings` **after** deps are
installed and `PYTHONPATH` is set, then checks
`settings.effective_arango_host` (not raw `os.environ`). This catches an
accidentally-set `ARANGO_ENDPOINT=http://localhost:8529` before uvicorn
boots, because no DB lives in the AOE pod.

To intentionally target loopback (CI, local repro):

```bash
AOE_ALLOW_LOOPBACK_ARANGO=1
```

---

## 5. Environment variables

### 5.1 Required

| Variable | Example | Notes |
|---------|---------|-------|
| `TEST_DEPLOYMENT_MODE` | `self_managed_platform` | Drives capability flags (`has_gae`, `is_cluster`, `can_create_databases`) |
| `ARANGO_ENDPOINT` | `https://cluster.example:8529` | Full URL with scheme + port |
| `ARANGO_DB` | `OntoExtract` | Database must exist (no `_system` access in self-managed mode) |
| `ARANGO_USER` | `aoe_service` | DB user |
| `ARANGO_PASSWORD` | `…` | DB password — prefer platform UI over `.env` |
| `ARANGO_VERIFY_SSL` | `true` | Required for production HTTPS |
| `APP_SECRET_KEY` | `<openssl rand -hex 32>` | Must not be the default in `APP_ENV=production` |
| `ANTHROPIC_API_KEY` *or* `OPENAI_API_KEY` | `sk-…` | At least one |

### 5.2 Recommended

| Variable | Example | Notes |
|---------|---------|-------|
| `APP_ENV` | `production` | Enables JWT enforcement on `/api/...` (except public routes) |
| `CORS_ORIGINS` | `https://host` | Comma-separated, no trailing slash |
| `SERVICE_URL_PATH_PREFIX` | `/_service/uds/_db/<db>/<svc>` | Required when behind a path-prefix ingress (see [`path-prefix-routing.md`](./path-prefix-routing.md)) |
| `REDIS_URL` | `redis://host:6379/0` | Set if rate limiting is enabled and Redis is available |
| `RATE_LIMIT_ENABLED` | `false` | Default-false-recommended in clusters without Redis to skip pointless `localhost:6379` connection attempts |

### 5.3 Optional / debugging

| Variable | Effect |
|---------|--------|
| `AOE_FRONTEND_OUT_DIR` / `FRONTEND_STATIC_ROOT` | Override the location of the Next static export (e.g. mounted from an external volume) |
| `AOE_SKIP_UV_SYNC=1` | Skip the `uv pip install` step at boot (use a pre-baked venv) |
| `AOE_ALLOW_LOOPBACK_ARANGO=1` | Allow `ARANGO_ENDPOINT=http://localhost:…` (defeats the loopback guard) |
| `UV_BINARY=/path/to/uv` | Pin the `uv` binary when `PATH` is minimal in the platform's launch shell |
| `APP_LOG_LEVEL` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

---

## 6. Bring-up procedure

1. **Edit repo-root `.env`** — set the required vars from §5.1 plus
   `SERVICE_URL_PATH_PREFIX` if the platform mounts you under a path.
2. **Build the bundle:**

   ```bash
   make package-arango-manual-all   # or backend-only: make package-arango-manual
   ```

3. **Upload `aoe-myservice.tar.gz`** to the Container Manager UI, choose
   `py13base` as the runtime image, and (optional) paste any sensitive env
   vars into the platform UI rather than shipping them in `.env`.
4. **Configure ingress / service URL** to point to the AOE pod under
   `SERVICE_URL_PATH_PREFIX`. The ingress should **route, not strip** —
   `StripServicePrefixMiddleware` does the strip inside FastAPI.
5. **Start the service.** Watch the logs for:

   - `using uv: /…/uv` — dependency installer found
   - `==> uv sync (lockfile)…` then `==> uv pip install -e .`
   - `Migrations complete`
   - `static_frontend_mounted` (with the resolved `frontend/out/<prefix>/`
     path) **or** `static_frontend_not_mounted` (expected if backend-only)
   - `Backend is ready.`

6. **Smoke-test:** see [`path-prefix-routing.md`](./path-prefix-routing.md)
   §7 for the full curl checklist.

---

## 7. Re-deploy / update

```bash
# 1. Edit code, commit
# 2. Rebuild the bundle
make package-arango-manual-all

# 3. Upload via Container Manager UI; Restart the service
# 4. Tail logs to confirm new code path:
#    - "Migrations complete" (if you added a migration)
#    - "static_frontend_mounted" with the new bundle path

# 5. Bust the cache (see path-prefix-routing.md §6 — "Cache caveat")
```

The trailing-slash ingress quirk and per-page Next chunk hashes can mask a
fresh deploy — confirm a known asset URL serves the new hash:

```bash
curl -sI https://<host>/<prefix>/_next/static/chunks/app/workspace/page-<newhash>.js
# 404 → bundle not deployed yet
# 200 → new bundle live; if browser still acts stale, hard-reload
```

---

## 8. Troubleshooting

### 8.1 "No entrypoint found"

The platform couldn't locate `./entrypoint` after extraction. Check the tar
layout:

```bash
tar -tzf aoe-myservice.tar.gz | head -5
# Want: ./entrypoint, ./pyproject.toml, … (flat)
# If you see: myservice/entrypoint, … and the platform expects flat, rebuild
# without PACKAGE_USE_TOPDIR=1.
```

### 8.2 `python /project/"""` (or other garbage) — entrypoint detection failed

Line 1 of `backend/entrypoint` must start with the literal token
`entrypoint`. A docstring, shebang, or import statement breaks this — see
§4.1.

### 8.3 `ModuleNotFoundError: No module named 'pip'` / `uv` not found

The venv has no `pip` and `uv` isn't on `PATH`. Two fixes:

- Set `UV_BINARY=/path/to/uv` so `_find_uv()` finds it explicitly.
- Or pre-bake the deps into the image and set `AOE_SKIP_UV_SYNC=1`.

### 8.4 `ARANGO_ENDPOINT=http://localhost:8529` errors at boot

The loopback guard tripped — see §4.6. Either point at the real cluster URL
or set `AOE_ALLOW_LOOPBACK_ARANGO=1` if you really mean it.

### 8.5 `.env` not picked up

Symptoms: `Settings` returns defaults despite the `.env` being in the
bundle. Check:

```bash
# Inside the running container
ls /project/.env                # bundled copy
python -c "from app.config import _resolved_env_files; print(_resolved_env_files())"
```

If empty, the file isn't where `_resolved_env_files()` looks. The fix is
usually rebuilding the bundle (the script copies `${REPO_ROOT}/.env` only
if it exists at build time).

### 8.6 Every SPA route returns 404

If the bundled `frontend/out/` exists but `/` and `/library` both 404,
either:

- **No `index.html` at the resolved root** — `resolve_frontend_out_dir`
  refuses to mount empty/placeholder directories. Confirm your build
  actually produced HTML files (rebuild with `make package-arango-manual-all`).
- **`SERVICE_URL_PATH_PREFIX` mismatch** — backend resolved
  `frontend/out/` but the build emitted files under
  `frontend/out/<oldprefix>/`. Rebuild with the matching prefix.
- **Vanilla `StaticFiles` instead of `NextStaticExportApp`** — see
  [ADR 007](./adr/007-spa-html-fallback.md). The mount in `app/main.py`
  must use `NextStaticExportApp(directory=..., html=True)`.

### 8.7 "Home" link goes to the bare ArangoDB login

The trailing-slash gotcha (see [`path-prefix-routing.md`](./path-prefix-routing.md)
§6). Confirm the link is a raw `<a href={withBasePath("/")}>`, not a
`<Link href="/">`. If the source already uses raw anchors, you're hitting a
stale browser/proxy cache for the page chunk — hard-reload.

### 8.8 Connection attempts to `localhost:6379` even when Redis isn't deployed

Set `RATE_LIMIT_ENABLED=false` (or a real `REDIS_URL`). The rate-limit
client now caches its `ping()` result and backs off after failures, but the
single startup attempt still surfaces in logs.

---

## 9. Security notes

- **`.env` in the tarball is convenient but sensitive.** For production,
  prefer **only** Container Manager UI env vars and exclude `.env` from the
  bundle (rename or move it before `make package-arango-manual…`).
- **`APP_SECRET_KEY`** must be unique per environment and **must not be the
  default** when `APP_ENV=production` — the app will refuse to issue JWTs.
- **JWT enforcement** applies to `/api/...` (except public routes). Health
  and readiness probes (`/health`, `/ready`) and the static export are
  intentionally public.
- Rotate `ARANGO_PASSWORD` and `APP_SECRET_KEY` regularly.

---

## 10. Related docs

- [`path-prefix-routing.md`](./path-prefix-routing.md) — how
  `SERVICE_URL_PATH_PREFIX` flows end-to-end (frontend `basePath`,
  `withBasePath`, `backendUrl`, backend strip middleware,
  `NextStaticExportApp`).
- [`adr/007-spa-html-fallback.md`](./adr/007-spa-html-fallback.md) — why
  `NextStaticExportApp` exists and what it solves.
- [`arango-cloud-deployment.md`](./arango-cloud-deployment.md) — the
  alternative Docker-image deployment path.
- [`architecture.md`](./architecture.md) — system architecture overview.

---

## 11. Files of interest

| Concern | Path |
|---------|------|
| Build script | `scripts/package-arango-manual.sh` |
| Make targets | `Makefile` (`package-arango-manual`, `package-arango-manual-all`) |
| Container entry | `backend/entrypoint` |
| Settings + env resolution | `backend/app/config.py` (`_resolved_env_files`, `SettingsConfigDict`) |
| Lockfile | `backend/uv.lock` (tracked via `.gitignore` `!backend/uv.lock`) |
| Static export resolver | `backend/app/frontend_static.py` |
| `<path>.html` fallback | `backend/app/static_export_app.py` |
| Strip middleware | `backend/app/middleware/strip_service_prefix.py` |
| Minimal `/login` HTML | `backend/app/minimal_login.py` |
| Rate limit resilience | `backend/app/api/rate_limit.py` |
| Tests | `backend/tests/unit/test_arango_manual_package.py`, `test_config_env_file_paths.py`, `test_static_export_app.py`, `test_frontend_static.py`, `test_strip_service_prefix.py`, `test_login_discovery.py`, `test_rate_limit.py` |
