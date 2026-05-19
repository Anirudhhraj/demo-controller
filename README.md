# Demo Controller

Lifecycle manager for GCE VM-hosted portfolio demos. Wakes them on demand,
tracks portfolio sessions, shuts down VMs that the portfolio started once
their sessions go idle. Manual/owner-started VMs are never auto-stopped.

## Local setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
gcloud auth application-default login
Copy-Item .env.example .env
# Edit .env and set ADMIN_TOKEN to a long random string.
```

## Run

```powershell
uvicorn app.main:app --reload --port 8080
```

Open http://localhost:8080/docs for the auto-generated API explorer.

## Adding a new demo

Add an entry to `demos.yaml`. No code changes.

## Architecture

- `app/config.py`  — loads `.env` + `demos.yaml` into typed objects.
- `app/compute.py` — wraps GCP Compute Engine start/stop/describe.
- `app/state.py`   — per-demo lifecycle state in a local JSON file
                     (swap for Firestore when deploying to Cloud Run).
- `app/reaper.py`  — the idle-shutdown decision logic.
- `app/routes/`    — FastAPI routers (public + admin).
- `app/auth.py`    — admin-token verification dependency.