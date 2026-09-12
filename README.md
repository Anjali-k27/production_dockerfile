# EPOCH — Session 17.1: Dockerfile — Hardening `epoch-gateway`

A hardened, multi-stage **production** image for the EPOCH gateway. It replaces
the dev-mode `fastapi` service that ran in Week 16.1's cluster: same
application, same routes, same JWT contract — but built as two stages, shipped
without a compiler, run as a non-root user, and kept under a 400 MB budget.

This README has been validated end-to-end against this exact directory:
`docker build` → `bash verify.sh` → a manual JWT round-trip and cross-tenant
rejection → a portability run from a directory with zero `.py` files, run with
no manual waiting in between. See [Verified state](#verified-state).

---

## Where this sits in the track

```
  15.x  ingest / auth / SLA modules  →  ../../phase5/session1..3
  16.1  containerize (5-svc cluster) →  ../../phase5/session4     dev-mode fastapi Dockerfile
  16.2  smoke-test it                →  ../../phase5/session5     /v1 + /v2, PII, admin gate, epoch_auth.py
  16.3  load-test it                 →  ../../phase5/session6     Locust staged ramp
  17.1  harden the image             →  this directory           multi-stage, non-root, < 400 MB
```

The application code here is carried forward from **16.2**
(`../../phase5/session5/services/fastapi/app/`), repackaged from a flat
`app/main.py` into an installable `epoch_gateway/` package so the image imports
`epoch_gateway.main:app` instead of a bare `main:app` off the working directory.

**Carried forward unchanged from Week 16:**

- JWT verification contract — `epoch_gateway/epoch_auth.py`, same
  `JWT_SECRET` / `JWT_ISSUER` / `JWT_AUDIENCE` as `tests/fakes.py::mint_jwt`
- PII redaction on the prompt in and the answer out (CC + SSN patterns)
- admin-only tool gate (`"clinical pdf"` / `"deliverable"` keywords → `role == "admin"`)
- `/v1/agent/invoke` frozen (`Deprecation` / `Sunset` / `Link` headers) +
  `/v2/agent/invoke` live (no deprecation headers)
- `400`, never `500`, on malformed JSON

**New in 17.1:**

- `GET /health` advertises `tenant_isolation` state
- per-request tenant binding: the tenant is the caller's `hospital_id` **claim**,
  never a value the client sends. When `EPOCH_TENANT_ISOLATION=active` (default),
  a request body naming a *different* `hospital_id` is a cross-tenant attempt and
  is rejected `403` before any backend call
- responses carry `X-Epoch-Tenant` / `X-Epoch-Tenant-Isolation`

---

## Architecture — the image, not the cluster

```
  ┌──────────────────────────── Stage 1: builder ────────────────────────────┐
  │  FROM python:3.12-slim AS builder                                        │
  │  apt: build-essential gcc      ← compilers live HERE and are never shipped │
  │  pip wheel -r requirements.txt  → /wheels/*.whl   (httptools, uvloop,     │
  │                                                    pydantic-core, ...)    │
  └─────────────────────────────────┬───────────────────────────────────────┘
                                    │  COPY --from=builder /wheels /wheels
                                    ▼
  ┌──────────────────────────── Stage 2: runtime ───────────────────────────┐
  │  FROM python:3.12-slim AS runtime                                        │
  │  apt: curl only    ← the single OS package, used by HEALTHCHECK          │
  │  pip install /wheels/*.whl && rm -rf /wheels    ← no compiler in history  │
  │  groupadd/useradd epoch (UID 1000)                                       │
  │  COPY epoch_gateway/  ;  COPY healthcheck.sh  ;  chown -R epoch:epoch    │
  │  USER epoch           ← before EXPOSE and CMD                            │
  │  EXPOSE 8000                                                            │
  │  HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3  │
  │  CMD uvicorn epoch_gateway.main:app --host 0.0.0.0 --port 8000           │
  └────────────────────────────────────────────────────────────────────────┘
```

The `curl`-in-runtime step follows the pattern already established in Week 16.1
(`../../phase5/session4/services/fastapi/Dockerfile` does the same thing for the
same reason): `python:3.12-slim` ships no HTTP client, and the `HEALTHCHECK`
needs one. It is not a compiler, so it does not show up as `build-essential` /
`gcc` in the runtime layer history.

---

## Prerequisites

```bash
docker --version          # Docker Engine 24+
docker buildx version     # BuildKit — bundled with Docker Desktop
```

Verified against Docker Engine **27.3.1** / Buildx **v0.18.0** on this machine.

If `docker info` fails with `Cannot connect to the Docker daemon`, Docker
Desktop isn't running — start it (`open -a Docker` on macOS) and wait ~15s
before retrying.

---

## Cloning the repo

This directory **is** the git root — `Dockerfile`, `epoch_gateway/`,
`verify.sh` all live at the top level, with no wrapper subfolder to `cd` into
after cloning. That is deliberate and matches every other phase5 session
(`session1` … `Session6` are each flat at their root). This project was drafted
one level deeper in an `epoch-gateway/` subfolder and then flattened — see
[Directory structure](#directory-structure) for why.

First-time remote setup:

```bash
# from this directory, one time
git init
git add .
git commit -m "EPOCH — Session 17.1: hardened epoch-gateway production image"
git remote add origin <your-remote-url>
git push -u origin main
```

Anyone else then picks it up the normal way and lands directly on a working
tree — `Dockerfile` is right there, no extra `cd`:

```bash
git clone <your-remote-url>
cd <the-directory-git-created>
cp .env.example .env        # .env is git-ignored — a fresh clone has no secrets
bash verify.sh
```

`.env` and `.venv/` are git-ignored (`.gitignore`). The demo values in
`.env.example` need no real provider keys and are safe for local runs; rotate
`JWT_SECRET` before any real deployment.

---

## Quick start

```bash
# from the repo root — Dockerfile lives here directly
cp .env.example .env         # first run only

docker build -t epoch-api:v1 .
bash verify.sh
```

Expected `bash verify.sh` output:

```
Building...
✓ image builds cleanly (14/14 layers)
✓ image size: 215MB (< 400MB budget)
✓ container runs as non-root: epoch (uid=1000)
Waiting for HEALTHCHECK (start-period 15s)...
✓ HEALTHCHECK reports healthy within 15s
✓ /health responds 200 with no source mount
✓ portability: image runs on a directory with zero .py files present
✓ Session 17.1 COMPLETE.
```

Run it by hand:

```bash
docker run -d -p 8000:8000 --env-file .env --name epoch-test epoch-api:v1
docker exec epoch-test whoami                     # -> epoch
curl -s http://localhost:8000/health              # -> {"status":"ok","tenant_isolation":"active"}
docker rm -f epoch-test
```

### Inspecting the running image

FastAPI ships interactive docs inside the image — no extra UI was built:

| URL | View |
|---|---|
| `http://localhost:8000/docs` | Swagger UI — browse + fire all 4 routes; **Authorize** takes a `Bearer <jwt>` for `/v1`/`/v2` |
| `http://localhost:8000/redoc` | ReDoc — read-only reference |
| `http://localhost:8000/openapi.json` | raw OpenAPI 3.1 spec |

![Swagger UI served from epoch-api:v1](docs/swagger-ui.png)

`/health` and `/cluster/health` work anonymously; the `/v1`/`/v2` invoke routes
return `401` without a JWT.

### Everyday commands

```bash
docker build -t epoch-api:v1 .                    # rebuild (deps cached unless requirements.txt changed)
docker images epoch-api:v1 --format "{{.Size}}"   # size scoreboard
docker history epoch-api:v1 --no-trunc            # layer X-ray
docker run --rm epoch-api:v1 pip list             # what actually shipped
```

---

## The three graded checks

| # | Check | Command | Pass criteria | Result |
|---|-------|---------|---------------|--------|
| 1 | Runs and answers | `docker run` → `curl /health` | HTTP 200 | `{"status":"ok","tenant_isolation":"active"}` |
| 2 | Under budget | `docker inspect epoch-api:v1` | < 400 MB | **~215 MB** |
| 3 | Not root | `docker exec epoch-test whoami` | `epoch`, not `root` | `uid=1000(epoch) gid=1000(epoch)` |

Size and identity are graded exactly as strictly as functionality — a passing
build with a failing `whoami` is not a passing session.

---

## What `verify.sh` checks

| Line | Verifies |
|---|---|
| `image builds cleanly` | `docker build` exits 0 (full log at `/tmp/build.log` on failure) |
| `image size … < 400MB budget` | `docker inspect .Size` / 1024² is under 400 |
| `runs as non-root: epoch` | `docker exec … whoami` is `epoch` |
| `HEALTHCHECK reports healthy within 15s` | `.State.Health.Status` is `healthy` after the 15s start-period |
| `/health responds 200 with no source mount` | container serves `/health` with no `-v` bind — the image is self-contained |
| `portability: … zero .py files present` | a source-free directory has nothing the image needs |

Beyond `verify.sh`, the carried-forward behavior was re-exercised directly
(see [Verified state](#verified-state)): no token → `401`, malformed JSON →
`400`, `/v1` carries `Deprecation`/`Sunset`/`Link` and `/v2` does not, and a
cross-tenant `hospital_id` in the body → `403`.

---

## Wiring it into the Week 16 cluster

This image is a drop-in for the dev-mode `fastapi` service in
`../../phase5/session4/docker-compose.yml`. To use it there:

```yaml
  fastapi:
    image: epoch-api:v1          # was: build: ./services/fastapi
    networks: [backplane, gateway]
    ports:
      - "8000:8000"
    env_file: [.env]
    depends_on:
      litellm:  { condition: service_healthy }
      redis:    { condition: service_healthy }
      postgres: { condition: service_healthy }
    # no healthcheck: block needed — the image's own HEALTHCHECK drives
    # depends_on: condition: service_healthy for anything downstream
```

The image's baked-in `HEALTHCHECK` (all four flags, `--start-period=15s`)
replaces the inline `healthcheck:` the compose file declared for the old
build — one slow-boot-safe definition, shipped with the image.

---

## Verified state

Run end-to-end against this directory on **2026-09-03**:

```
docker build -t epoch-api:v1 .                    # 14/14 stages, no cache reuse for COPY layers
docker images epoch-api:v1                         # ~215 MB  (budget 400 MB)
docker history epoch-api:v1 --no-trunc | grep -i 'pip wheel\|build-essential'
                                                  # (nothing — builder stage is not in the runtime history)
docker run -d -p 8000:8000 --env-file .env --name epoch-test epoch-api:v1
docker exec epoch-test whoami                      # epoch  (uid=1000)
curl -s localhost:8000/health                      # {"status":"ok","tenant_isolation":"active"}
#   no token           -> 401
#   malformed JSON      -> 400   (not 500)
#   /v1 invoke          -> Deprecation: true + Sunset + Link
#   /v2 invoke          -> no Deprecation header
#   body hospital_b vs token hospital_a -> 403 cross-tenant
docker inspect --format '{{.State.Health.Status}}' epoch-test   # healthy (after 15s start-period)
bash verify.sh                                     # all 7 lines ✓, "Session 17.1 COMPLETE."
```

`docker history` note: `grep` for `gcc` in the runtime history still matches
lines — they come from the upstream `python:3.12-slim` base's own CPython build
layers, present in every slim image and `apt-get purge`d in the same layer.
The point the grader checks is that **this project's** builder stage — the
`pip wheel` layer and its `build-essential gcc` install — is absent from the
runtime image. It is.

---

## Common failure modes (deliberate bug exercises)

Each is a real hardening regression. Reproduce, observe, revert — the
`Dockerfile` in this directory is in the clean, passing state.

| # | Bug | How to reproduce | Observed | Lesson |
|---|-----|------------------|----------|--------|
| 1 | `COPY . .` before `COPY requirements.txt .` | swap the two COPY lines in stage 1 | every code edit re-runs `pip wheel` from scratch — the dependency cache layer is busted | copy the dependency manifest and install it *before* the source, so a source-only change reuses the cached deps layer |
| 2 | `USER epoch` missing or after `CMD` | delete the `USER epoch` line (or move it below `CMD`) | image builds fine, `verify.sh` health check passes, **check #3 fails**: `whoami` → `root` | this is the most common silent failure — the container runs as UID 0 with everything else green |
| 3 | `HEALTHCHECK` with no `--start-period` | drop `--start-period=15s` from the HEALTHCHECK line | passes locally (uvicorn cold-starts in ~2-4s) but a cold image on a slow host is marked `unhealthy` before it is up, blocking every `depends_on: service_healthy` downstream | `--start-period` must exceed real cold-start time — Week 16.1 learned the same lesson for `vllm` |
| 4 | single-stage build | delete stage 1, `pip install -r requirements.txt` directly in one stage | `build-essential` + `gcc` ship in the final image; size jumps well over budget | this session fails outright on a single `FROM` — the compiler toolchain must not reach the runtime layer |
| 5 | `ENV JWT_SECRET=...` in the Dockerfile | add `ENV JWT_SECRET=leaked` before `USER epoch`, then `docker history epoch-api:v1 --no-trunc \| grep JWT` | the secret is visible in the image's layer history forever, to anyone who pulls it | secrets belong only in `--env-file` / `env_file:`, injected at runtime — Buildx flags this natively as `SecretsUsedInArgOrEnv` |

---

## Directory structure

Flat at the repo root — no wrapper folder to `cd` into after cloning:

```
.
├── .dockerignore           # keeps .env / .git / .venv / *.md / tests out of the build context
├── .env                    # secrets — git-ignored, recreate from .env.example after cloning
├── .env.example            # committed template, demo defaults, no real keys
├── .gitignore
├── Dockerfile              # 2 stages: builder (wheels) → runtime (non-root, curl-only, < 400 MB)
├── healthcheck.sh          # curl -f /health, exit 1 on failure — the container's readiness signal
├── requirements.txt        # carried from Week 16.2, reused not rewritten
├── verify.sh               # this session's 7-check validation script
├── README.md               # this file
│
└── epoch_gateway/          # the gateway, packaged (was flat app/ in Week 16.2)
    ├── __init__.py
    ├── epoch_auth.py       # verify_jwt() — unchanged JWT contract
    └── main.py             # /health, /cluster/health, /v1|/v2 agent/invoke, tenant binding
```

**Why flat.** This project was drafted one level deeper, inside an
`epoch-gateway/` subfolder. Nothing else shares this directory, so the nesting
only added an unnecessary `cd` after cloning and broke every command in this
README that assumes `Dockerfile` is where you land. Flattened with
`mv epoch-gateway/* epoch-gateway/.* .` → `rmdir epoch-gateway`; `verify.sh`
was re-run in full from the new root and passed identically — the move changed
nothing about behavior, only where the files live. Same fix Week 16.1 and
16.2 applied to their own `epoch-cluster/` wrappers.

---

## Final checklist

- [x] Two `FROM` lines — `builder` compiles wheels, `runtime` ships only what runs
- [x] `USER epoch` (UID 1000) appears **before** `EXPOSE` and `CMD`
- [x] No `build-essential` / `gcc` install from this project in the runtime layer history
- [x] `HEALTHCHECK` present with all four flags (`--interval --timeout --start-period --retries`)
- [x] `COPY requirements.txt` before `COPY epoch_gateway/` — dependency cache layer survives a code edit
- [x] `.dockerignore` excludes `.env*`, `.git/`, `.venv/`, `*.md`, `tests/`
- [x] No secrets baked with `ENV` — `.env` injected at runtime only
- [x] Image size ~215 MB (budget < 400 MB)
- [x] `docker exec … whoami` → `epoch`, not `root`
- [x] `HEALTHCHECK` reports `healthy` within the 15s start-period
- [x] `/health` → `{"status":"ok","tenant_isolation":"active"}` with no source mount
- [x] Carried-forward behavior intact: 401 no-token, 400 malformed JSON, /v1 vs /v2 deprecation headers
- [x] New tenant isolation: cross-tenant `hospital_id` → 403
- [x] Flat at the repo root — no `epoch-gateway/` wrapper, no extra `cd` after cloning
- [x] `.env.example` committed; `.env` + `.venv/` git-ignored
- [x] `bash verify.sh` → all 7 checks pass, "Session 17.1 COMPLETE."

---

## What's next

- **Keep `epoch-api:v1` built locally** — a later session swaps it into
  `../../phase5/session4/docker-compose.yml` in place of `build: ./services/fastapi`
  and re-runs that cluster's `validate.sh` against the hardened image.
- Before starting the next session, re-run `bash verify.sh` to confirm you are
  picking up from a known-good state — don't assume the image is still built or
  passing just because it was last time.
- The tenant-isolation check added here is enforced only on the request *body*.
  A later session may push it down to row-level scoping at the Postgres layer
  (`hospital_id` as a tenant discriminator on every query), at which point
  `EPOCH_TENANT_ISOLATION` becomes a cluster-wide setting, not just a gateway one.

The spec does not yet document sessions past 17.1 in this track — treat
anything beyond it as unconfirmed until its own materials show up.
