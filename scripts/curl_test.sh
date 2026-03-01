#!/usr/bin/env bash
# curl_test.sh — End-to-end command + error + lifecycle tests
#
# Prerequisites:
#   1. Server running:  cd /home/faros/faros-server && .venv/bin/faros-server run
#   2. Agent running:   cd /home/faros/faros && .venv/bin/faros-agent run --config deploy_config.yaml
#   3. JWT token from browser dev tools (faros_token cookie after OAuth login)
#
# Usage:
#   bash scripts/curl_test.sh --jwt=<token>
#   bash scripts/curl_test.sh --jwt=<token> --skip-destructive
#
# --skip-destructive: skip Test 13 (Logout) so the agent stays running
#                     and you can re-run the script.
#
# Reads agent credentials from ~/.faros/credentials.json automatically.
# Tests 7-11 (TTL) require a server restart with FAROS_COMMAND_TTL_SECONDS=1
# and are NOT included here — run those manually per docs/curl_test_commands.md.

set -euo pipefail

# ---------------------------------------------------------------------------
# Parse args
# ---------------------------------------------------------------------------
JWT=""
SKIP_DESTRUCTIVE=false
for arg in "$@"; do
  case "$arg" in
    --jwt=*) JWT="${arg#--jwt=}" ;;
    --skip-destructive) SKIP_DESTRUCTIVE=true ;;
    *) echo "Usage: bash scripts/curl_test.sh --jwt=<token> [--skip-destructive]" >&2; exit 1 ;;
  esac
done
if [ -z "$JWT" ]; then
  echo "Error: --jwt=<token> is required" >&2
  echo "  Get it from the faros_token cookie in browser dev tools after OAuth login." >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Read agent credentials
# ---------------------------------------------------------------------------
CREDS="$HOME/.faros/credentials.json"
if [ ! -f "$CREDS" ]; then
  echo "Error: $CREDS not found — start the agent first" >&2
  exit 1
fi

API_KEY=$(python3 -c "import json; print(json.load(open('$CREDS'))['api_key'])")
AGENT_ID=$(python3 -c "import json; print(json.load(open('$CREDS'))['agent_id'])")
AUTH_AGENT="Authorization: Bearer $API_KEY"
AUTH_OP="Authorization: Bearer $JWT"
SERVER="http://localhost:8000"

PASS=0
FAIL=0
POLL_TIMEOUT=15  # max seconds to wait for agent to ack

echo "=== Faros E2E Command Tests ==="
echo "  agent_id: $AGENT_ID"
if $SKIP_DESTRUCTIVE; then
  echo "  mode: --skip-destructive (Tests 13-14 skipped)"
fi
echo ""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
check() {
  local label="$1" expected="$2" actual="$3"
  if [ "$actual" = "$expected" ]; then
    echo "  PASS  $label (got $actual)"
    PASS=$((PASS + 1))
  else
    echo "  FAIL  $label (expected $expected, got $actual)"
    FAIL=$((FAIL + 1))
  fi
}

queue_cmd() {
  # Queue a command and return its id
  local payload="$1"
  local resp
  resp=$(curl -s -X POST "$SERVER/api/agents/$AGENT_ID/commands" \
    -H 'Content-Type: application/json' -H "$AUTH_OP" \
    -d "$payload")
  echo "$resp" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])"
}

get_status() {
  # Get the status field of a command
  local cmd_id="$1"
  curl -s "$SERVER/api/agents/$AGENT_ID/commands/$cmd_id" -H "$AUTH_OP" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])"
}

wait_for_status() {
  # Poll until command reaches expected status or timeout
  local cmd_id="$1" expected="$2" timeout="${3:-$POLL_TIMEOUT}"
  local elapsed=0
  while [ "$elapsed" -lt "$timeout" ]; do
    local status
    status=$(get_status "$cmd_id")
    if [ "$status" = "$expected" ]; then
      echo "$status"
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  # Return whatever we got last
  get_status "$cmd_id"
}

get_http_code() {
  # Return just the HTTP status code
  local method="$1" url="$2" auth="$3" body="${4:-}"
  if [ -n "$body" ]; then
    curl -s -o /dev/null -w "%{http_code}" -X "$method" "$url" \
      -H 'Content-Type: application/json' -H "$auth" -d "$body"
  else
    curl -s -o /dev/null -w "%{http_code}" -X "$method" "$url" \
      -H "$auth"
  fi
}

# ---------------------------------------------------------------------------
# Test 1: TestLongRunning — full lifecycle with output streaming
# ---------------------------------------------------------------------------
echo "== Test 1: TestLongRunning (3 steps, 1s each) =="
TLR_ID=$(queue_cmd '{"type": "TestLongRunning", "payload": {"steps": 3, "step_delay_s": 1.0}}')
echo "  queued: $TLR_ID"

# Wait for agent to pick it up
MID_STATUS=$(wait_for_status "$TLR_ID" "in_progress" 5)
check "mid-flight status" "in_progress" "$MID_STATUS"

# Wait for acked
FINAL_STATUS=$(wait_for_status "$TLR_ID" "acked" 10)
check "final status" "acked" "$FINAL_STATUS"

FINAL_RESULT=$(curl -s "$SERVER/api/agents/$AGENT_ID/commands/$TLR_ID" -H "$AUTH_OP" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('result',{}).get('success',''))")
check "result.success" "True" "$FINAL_RESULT"

# Save CMD_ID for later error-case tests
CMD_ID="$TLR_ID"
echo ""

# ---------------------------------------------------------------------------
# Test 2: Output on pending command (expect 409)
# ---------------------------------------------------------------------------
echo "== Test 2: Output on pending command =="
# Must be faster than the agent's poll interval
T2_ID=$(queue_cmd '{"type": "Status"}')
echo "  queued: $T2_ID"
HTTP=$(get_http_code POST "$SERVER/api/agents/commands/$T2_ID/output" "$AUTH_AGENT" '{"output": "should fail"}')
check "output on pending" "409" "$HTTP"
# Let the agent clean it up
wait_for_status "$T2_ID" "acked" > /dev/null 2>&1 || true
echo ""

# ---------------------------------------------------------------------------
# Test 3: All command types (agent handles automatically)
# ---------------------------------------------------------------------------
echo "== Test 3: All command types =="

queue_and_check() {
  local label="$1" payload="$2"
  local cid
  cid=$(queue_cmd "$payload")
  echo "  $label: queued $cid"
  local status
  status=$(wait_for_status "$cid" "acked")
  check "$label" "acked" "$status"
}

queue_and_check "Discover" '{"type": "Discover"}'
queue_and_check "Register" '{"type": "Register"}'
queue_and_check "Validate" '{"type": "Validate"}'
queue_and_check "ModelDeploy" \
  '{"type": "ModelDeploy", "payload": {"group": "drivetrain", "onnx_url": "http://example.com/model.onnx", "artifact_url": "http://example.com/artifact.yaml"}}'
queue_and_check "ConfigUpdate" \
  '{"type": "ConfigUpdate", "payload": {"config_url": "http://example.com/deploy_config.yaml"}}'
queue_and_check "CollectStart" \
  '{"type": "CollectStart", "payload": {"topics": ["/imu", "/odom"], "duration_s": 10}}'
queue_and_check "CollectStop" '{"type": "CollectStop"}'
queue_and_check "Status" '{"type": "Status"}'
queue_and_check "Status (sections)" \
  '{"type": "Status", "payload": {"sections": ["health"]}}'
echo ""

# ---------------------------------------------------------------------------
# Test 4: List all commands (operator view)
# ---------------------------------------------------------------------------
echo "== Test 4: List all commands =="
LIST_COUNT=$(curl -s "$SERVER/api/agents/$AGENT_ID/commands" -H "$AUTH_OP" \
  | python3 -c "import sys,json; print(len(json.load(sys.stdin)))")
echo "  commands listed: $LIST_COUNT"
if [ "$LIST_COUNT" -gt 0 ]; then
  echo "  PASS  operator can list commands"
  PASS=$((PASS + 1))
else
  echo "  FAIL  operator got 0 commands"
  FAIL=$((FAIL + 1))
fi
echo ""

# ---------------------------------------------------------------------------
# Test 5: Error cases
# ---------------------------------------------------------------------------
echo "== Test 5: Error cases =="

# No auth → 401
HTTP=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "$SERVER/api/agents/commands/fake/output" \
  -H 'Content-Type: application/json' -d '{"output": "x"}')
check "no auth" "401" "$HTTP"

# Nonexistent command → 404
HTTP=$(get_http_code POST "$SERVER/api/agents/commands/nonexistent/output" "$AUTH_AGENT" '{"output": "x"}')
check "nonexistent command" "404" "$HTTP"

# Empty output → 400
HTTP=$(get_http_code POST "$SERVER/api/agents/commands/$CMD_ID/output" "$AUTH_AGENT" '{"output": ""}')
check "empty output" "400" "$HTTP"

# Output on acked command → 409
HTTP=$(get_http_code POST "$SERVER/api/agents/commands/$CMD_ID/output" "$AUTH_AGENT" '{"output": "too late"}')
check "output on acked" "409" "$HTTP"
echo ""

# ---------------------------------------------------------------------------
# Test 12: Heartbeat
# ---------------------------------------------------------------------------
echo "== Test 12: Heartbeat =="
HTTP=$(get_http_code POST "$SERVER/api/agents/heartbeat" "$AUTH_AGENT" '{"uptime_s": 120, "cpu_pct": 3.2}')
check "heartbeat" "200" "$HTTP"
echo ""

# ---------------------------------------------------------------------------
# Test 13: Logout command (agent acks, revokes key, removes creds, exits)
# ---------------------------------------------------------------------------
if $SKIP_DESTRUCTIVE; then
  echo "== Test 13: Logout command == SKIPPED (--skip-destructive)"
  echo ""
else
  echo "== Test 13: Logout command =="
  LOGOUT_ID=$(queue_cmd '{"type": "Logout"}')
  echo "  queued: $LOGOUT_ID"
  LOGOUT_STATUS=$(wait_for_status "$LOGOUT_ID" "acked")
  check "logout acked" "acked" "$LOGOUT_STATUS"

  # Agent needs time to stop threads and run post-stop logout
  sleep 8
  HTTP=$(get_http_code GET "$SERVER/api/agents/commands" "$AUTH_AGENT")
  check "key revoked" "401" "$HTTP"
  echo ""
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
TOTAL=$((PASS + FAIL))
echo "==============================="
echo "  $PASS/$TOTAL passed, $FAIL failed"
echo "==============================="
echo ""
echo "NOTE: Tests 6-11 (TTL) require a server restart with"
echo "  FAROS_COMMAND_TTL_SECONDS=1 — run those manually per"
echo "  docs/curl_test_commands.md"

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
