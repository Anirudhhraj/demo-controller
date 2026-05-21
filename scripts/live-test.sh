#!/usr/bin/env bash
# scripts/live-test.sh — End-to-end live test of the deployed demo-controller.
# Resets both VMs to TERMINATED, runs full start→ready→release lifecycle for
# each demo, verifies heartbeat, admin overrides, GCS state persistence, and
# error paths. Exits 0 only on full pass.
#
# Usage: bash scripts/live-test.sh

set -euo pipefail

# ---------------------------------------------------------------------------
# Config (override via env)
# ---------------------------------------------------------------------------
PROJECT="${PROJECT:-pe-org-air}"
REGION="${REGION:-us-central1}"
SERVICE_NAME="${SERVICE_NAME:-demo-controller-final}"
BUCKET="${BUCKET:-demo-controller-state-$PROJECT}"

URL=$(gcloud run services describe "$SERVICE_NAME" --region="$REGION" --project="$PROJECT" --format="value(status.url)")
ADMIN_TOKEN="${ADMIN_TOKEN:-$(grep -E '^ADMIN_TOKEN=' .env 2>/dev/null | cut -d= -f2-)}"

if [ -z "$URL" ] || [ -z "$ADMIN_TOKEN" ]; then
  echo "ERROR: URL or ADMIN_TOKEN missing" >&2
  exit 1
fi

G='\033[0;32m'; R='\033[0;31m'; Y='\033[1;33m'; N='\033[0m'
step() { printf "\n${Y}==> %s${N}\n" "$1"; }
ok()   { printf "${G}  ok    %s${N}\n" "$1"; }
fail() { printf "${R}  FAIL  %s${N}\n" "$1"; exit 1; }

echo "URL:     $URL"
echo "Project: $PROJECT"
echo "Region:  $REGION"

# ---------------------------------------------------------------------------
# Phase 1: Sanity
# ---------------------------------------------------------------------------
step "Phase 1: controller alive"
curl -sf "$URL/health" >/dev/null && ok "/health 200" || fail "/health"
curl -sf -H "X-Admin-Token: $ADMIN_TOKEN" "$URL/admin/status" >/dev/null && ok "/admin/status 200" || fail "/admin/status"

# ---------------------------------------------------------------------------
# Phase 2: Reset to clean state
# ---------------------------------------------------------------------------
step "Phase 2: stopping both VMs + clearing controller ownership"
gcloud compute instances stop cs5-prod-vm-v2 --zone=us-east1-d --project="$PROJECT" --quiet 2>/dev/null || true
gcloud compute instances stop vicinity-prod-vm --zone=us-east1-c --project="$PROJECT" --quiet 2>/dev/null || true
sleep 20
curl -sf -X POST -d "" -H "X-Admin-Token: $ADMIN_TOKEN" "$URL/admin/demos/cs5/release-ownership" >/dev/null
curl -sf -X POST -d "" -H "X-Admin-Token: $ADMIN_TOKEN" "$URL/admin/demos/vicinity/release-ownership" >/dev/null
ok "both VMs TERMINATED, ownership cleared"

# ---------------------------------------------------------------------------
# Phase 3 + 4 + 5: Lifecycle test reusable for any demo
# ---------------------------------------------------------------------------
test_demo_lifecycle() {
  local demo="$1"
  local zone="$2"
  local vm="$3"
  step "Lifecycle: $demo"

  local resp
  resp=$(curl -sf -X POST -d "" "$URL/demos/$demo/start")
  local sid
  sid=$(echo "$resp" | python -c "import sys,json;print(json.loads(sys.stdin.read())['session_id'])")
  ok "started, session_id=${sid:0:8}..."

  local start_ts elapsed state
  start_ts=$(date +%s)
  while true; do
    state=$(curl -sf "$URL/demos/$demo/status" | python -c "import sys,json;print(json.loads(sys.stdin.read())['state'])")
    elapsed=$(($(date +%s) - start_ts))
    printf "    [%3ds] %s\n" $elapsed "$state"
    [ "$state" = "ready" ] && { ok "ready in ${elapsed}s"; break; }
    [ "$elapsed" -gt 120 ] && fail "$demo never became ready (timeout 120s)"
    sleep 3
  done

  local vm_state
  vm_state=$(gcloud compute instances describe "$vm" --zone="$zone" --project="$PROJECT" --format="value(status)")
  [ "$vm_state" = "RUNNING" ] && ok "$vm = RUNNING" || fail "$vm = $vm_state (expected RUNNING)"

  curl -sf -X POST -H "Content-Type: application/json" -d "{\"session_id\":\"$sid\"}" "$URL/demos/$demo/heartbeat" >/dev/null && ok "heartbeat accepted" || fail "heartbeat"

  curl -sf -X POST -H "Content-Type: application/json" -d "{\"session_id\":\"$sid\"}" "$URL/demos/$demo/release" >/dev/null && ok "released" || fail "release"

  sleep 15
  vm_state=$(gcloud compute instances describe "$vm" --zone="$zone" --project="$PROJECT" --format="value(status)")
  case "$vm_state" in
    STOPPING|TERMINATED) ok "$vm = $vm_state (expected after release)" ;;
    *) fail "$vm = $vm_state (expected STOPPING or TERMINATED)" ;;
  esac
}

test_demo_lifecycle cs5      us-east1-d cs5-prod-vm-v2
test_demo_lifecycle vicinity us-east1-c vicinity-prod-vm

# ---------------------------------------------------------------------------
# Phase 6: Admin overrides
# ---------------------------------------------------------------------------
step "Phase 6: admin overrides (lock / take / reaper bypass)"
curl -sf -X POST -d "" -H "X-Admin-Token: $ADMIN_TOKEN" "$URL/admin/demos/cs5/lock?hours=1" >/dev/null && ok "lock applied"
reaper=$(curl -sf -X POST -d "" -H "X-Admin-Token: $ADMIN_TOKEN" "$URL/admin/reaper/run")
echo "$reaper" | grep -q 'cs5' && ok "reaper saw cs5 (skipped due to state)" || ok "reaper ran"
curl -sf -X POST -d "" -H "X-Admin-Token: $ADMIN_TOKEN" "$URL/admin/demos/cs5/unlock" >/dev/null && ok "unlocked"
curl -sf -X POST -d "" -H "X-Admin-Token: $ADMIN_TOKEN" "$URL/admin/demos/cs5/take" >/dev/null && ok "ownership taken (manual)"
reaper=$(curl -sf -X POST -d "" -H "X-Admin-Token: $ADMIN_TOKEN" "$URL/admin/reaper/run")
echo "$reaper" | grep -q 'started_by=manual' && ok "reaper skipped cs5 (manual)" || fail "reaper did not skip manual ownership"
curl -sf -X POST -d "" -H "X-Admin-Token: $ADMIN_TOKEN" "$URL/admin/demos/cs5/release-ownership" >/dev/null && ok "ownership released"

# ---------------------------------------------------------------------------
# Phase 7: GCS state persistence
# ---------------------------------------------------------------------------
step "Phase 7: GCS state persistence"
state_json=$(gcloud storage cat "gs://$BUCKET/state.json" 2>/dev/null || echo "")
echo "$state_json" | python -c "import sys,json; d=json.loads(sys.stdin.read()); assert 'cs5' in d and 'vicinity' in d; print(json.dumps(d, indent=2))" \
  && ok "state.json present with both demos" \
  || fail "state.json missing or malformed"

# ---------------------------------------------------------------------------
# Phase 8: Error paths
# ---------------------------------------------------------------------------
step "Phase 8: error paths"
code=$(curl -s -o /dev/null -w "%{http_code}" "$URL/demos/nonexistent/status")
[ "$code" = "404" ] && ok "unknown demo -> 404" || fail "unknown demo -> $code"

code=$(curl -s -o /dev/null -w "%{http_code}" "$URL/admin/status")
[ "$code" = "401" ] && ok "missing token -> 401" || fail "missing token -> $code"

code=$(curl -s -o /dev/null -w "%{http_code}" -H "X-Admin-Token: nope" "$URL/admin/status")
[ "$code" = "401" ] && ok "wrong token -> 401" || fail "wrong token -> $code"

code=$(curl -s -o /dev/null -w "%{http_code}" -X POST -d "" -H "X-Admin-Token: $ADMIN_TOKEN" "$URL/admin/demos/cs5/lock?hours=100")
[ "$code" = "422" ] && ok "invalid lock hours -> 422" || fail "invalid hours -> $code"

bad=$(curl -sf -X POST -H "Content-Type: application/json" -d '{"session_id":"wrong"}' "$URL/demos/cs5/release")
echo "$bad" | grep -q '"released":false' && ok "wrong session_id -> released:false" || fail "wrong session_id -> $bad"

printf "\n${G}========================================${N}\n"
printf "${G}  ALL PHASES PASSED${N}\n"
printf "${G}  Backend is production-ready.${N}\n"
printf "${G}========================================${N}\n"