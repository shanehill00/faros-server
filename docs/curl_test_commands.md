# End-to-End curl Test: Commands + TTL

Test all command endpoints against a running server and agent.

**Automated script:** `bash scripts/curl_test.sh --jwt=<token>` runs Tests 1-5, 12-14 automatically.
Tests 6-11 (TTL) require a server restart and must be run manually below.

**1. Start the server:**

```bash
cd /home/faros/faros-server && .venv/bin/faros-server run
```

**2. Start the agent** (it will do device-flow login on first run — approve in browser):

```bash
cd /home/faros/faros && .venv/bin/faros-agent run --config deploy_config.yaml
```

---

## Setup: Set Auth Variables

The agent saves its credentials to `~/.faros/credentials.json` after login.
Read them from there so curl targets the same agent the running process uses.

```bash
API_KEY=$(python3 -c "import json; print(json.load(open('$HOME/.faros/credentials.json'))['api_key'])")
AGENT_ID=$(python3 -c "import json; print(json.load(open('$HOME/.faros/credentials.json'))['agent_id'])")
AUTH_AGENT="Authorization: Bearer $API_KEY"
echo "agent_id=$AGENT_ID"
```

For operator endpoints, grab the `faros_token` cookie from your browser dev tools after OAuth login:

```bash
JWT="<paste your faros_token cookie here>"
AUTH_OP="Authorization: Bearer $JWT"
```

---

## Test 1: TestLongRunning — End-to-End Output Streaming

Queue a `TestLongRunning` command. The agent handler sleeps between steps and
streams output to the server automatically — no manual curl needed for the
output phase. This exercises the full lifecycle: queue -> poll -> stream output -> ack.

### Operator queues TestLongRunning

```bash
QUEUED=$(curl -s -X POST "http://localhost:8000/api/agents/$AGENT_ID/commands" \
  -H 'Content-Type: application/json' -H "$AUTH_OP" \
  -d '{"type": "TestLongRunning", "payload": {"steps": 3, "step_delay_s": 1.0}}')
echo "QUEUED: $QUEUED"
CMD_ID=$(echo "$QUEUED" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
```

### Agent polls and runs (happens automatically)

The agent picks up the command, runs 3 steps (1s each), posting
`Step 1/3...`, `Step 2/3...`, `Step 3/3...` output, then acks with success.

### Operator checks progress mid-flight (run within ~2s of queueing)

```bash
curl -s "http://localhost:8000/api/agents/$AGENT_ID/commands/$CMD_ID" \
  -H "$AUTH_OP" | python3 -m json.tool
```

**Expected:** `status: "in_progress"`, partial `output` visible.

### Operator sees final state (after ~4s)

```bash
curl -s "http://localhost:8000/api/agents/$AGENT_ID/commands/$CMD_ID" \
  -H "$AUTH_OP" | python3 -m json.tool
```

**Expected:** `status: "acked"`, `output` contains all 3 step lines, `result.success: true`, `result.message: "Completed 3 steps."`.

---

## Test 2: Output on Pending Command (expect 409)

Queue a command and immediately try to post output before the agent polls it.
This must be fast — the agent polls every ~2s.

```bash
QUEUED2=$(curl -s -X POST "http://localhost:8000/api/agents/$AGENT_ID/commands" \
  -H 'Content-Type: application/json' -H "$AUTH_OP" \
  -d '{"type": "Status"}')
CMD_ID2=$(echo "$QUEUED2" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
curl -s -w "\nHTTP %{http_code}\n" \
  -X POST "http://localhost:8000/api/agents/commands/$CMD_ID2/output" \
  -H 'Content-Type: application/json' -H "$AUTH_AGENT" \
  -d '{"output": "should fail"}'
```

**Expected:** HTTP 409

---

## Test 3: All Command Types (Agent Handles Automatically)

Queue each command type and let the running agent poll, handle, and ack.
Commands with required payload fields get proper payloads.

```bash
queue_and_wait() {
  local label="$1" payload="$2"
  echo "--- $label ---"
  Q=$(curl -s -X POST "http://localhost:8000/api/agents/$AGENT_ID/commands" \
    -H 'Content-Type: application/json' -H "$AUTH_OP" \
    -d "$payload")
  CID=$(echo "$Q" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
  echo "  queued: $CID"
  sleep 3
  STATUS=$(curl -s "http://localhost:8000/api/agents/$AGENT_ID/commands/$CID" -H "$AUTH_OP")
  echo "  $(echo "$STATUS" | python3 -c "import sys, json; \
    d = json.load(sys.stdin); \
    print(f'status={d[\"status\"]}  result={d.get(\"result\")}')")"
}

queue_and_wait "Discover" '{"type": "Discover"}'
queue_and_wait "Register" '{"type": "Register"}'
queue_and_wait "Validate" '{"type": "Validate"}'
queue_and_wait "ModelDeploy" \
  '{"type": "ModelDeploy", "payload": {"group": "drivetrain", "onnx_url": "http://example.com/model.onnx", "artifact_url": "http://example.com/artifact.yaml"}}'
queue_and_wait "ConfigUpdate" \
  '{"type": "ConfigUpdate", "payload": {"config_url": "http://example.com/deploy_config.yaml"}}'
queue_and_wait "CollectStart" \
  '{"type": "CollectStart", "payload": {"topics": ["/imu", "/odom"], "duration_s": 10}}'
queue_and_wait "CollectStop" '{"type": "CollectStop"}'
queue_and_wait "Status" '{"type": "Status"}'
queue_and_wait "Status (sections)" \
  '{"type": "Status", "payload": {"sections": ["health"]}}'
```

**Expected:** All commands show `status=acked`.

---

## Test 4: List All Commands (Operator View)

```bash
curl -s "http://localhost:8000/api/agents/$AGENT_ID/commands" \
  -H "$AUTH_OP" | python3 -m json.tool
```

---

## Test 5: Error Cases

### No auth (expect 401)

```bash
curl -s -w "HTTP %{http_code}\n" \
  -X POST "http://localhost:8000/api/agents/commands/fake/output" \
  -H 'Content-Type: application/json' -d '{"output": "x"}'
```

### Nonexistent command (expect 404)

```bash
curl -s -w "\nHTTP %{http_code}\n" \
  -X POST "http://localhost:8000/api/agents/commands/nonexistent/output" \
  -H 'Content-Type: application/json' -H "$AUTH_AGENT" \
  -d '{"output": "x"}'
```

### Empty output (expect 400)

```bash
curl -s -w "\nHTTP %{http_code}\n" \
  -X POST "http://localhost:8000/api/agents/commands/$CMD_ID/output" \
  -H 'Content-Type: application/json' -H "$AUTH_AGENT" \
  -d '{"output": ""}'
```

### Output on acked command (expect 409)

```bash
curl -s -w "\nHTTP %{http_code}\n" \
  -X POST "http://localhost:8000/api/agents/commands/$CMD_ID/output" \
  -H 'Content-Type: application/json' -H "$AUTH_AGENT" \
  -d '{"output": "too late"}'
```

---

## Test 6: Command TTL — Fresh Command Delivered

Queue a command within the default 30s TTL. The agent picks it up and acks automatically.

```bash
API_KEY=$(python3 -c "import json; print(json.load(open('$HOME/.faros/credentials.json'))['api_key'])")
AGENT_ID=$(python3 -c "import json; print(json.load(open('$HOME/.faros/credentials.json'))['agent_id'])")
AUTH_AGENT="Authorization: Bearer $API_KEY"

FRESH=$(curl -s -X POST "http://localhost:8000/api/agents/$AGENT_ID/commands" \
  -H 'Content-Type: application/json' -H "$AUTH_OP" \
  -d '{"type": "Status"}')
echo "QUEUED: $FRESH"
FRESH_ID=$(echo "$FRESH" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

sleep 3

curl -s "http://localhost:8000/api/agents/$AGENT_ID/commands/$FRESH_ID" \
  -H "$AUTH_OP" | python3 -m json.tool
```

**Expected:** `status: "acked"` — the command was delivered and handled within the TTL.

---

## Test 7: Command TTL — Stale Command Expired

Restart the server with a very short TTL (1 second), queue a command, wait, then poll.

**Stop the server, then restart with TTL=1:**

```bash
FAROS_COMMAND_TTL_SECONDS=1 .venv/bin/faros-server run
```

Queue a command and wait 2 seconds before polling:

```bash
API_KEY=$(python3 -c "import json; print(json.load(open('$HOME/.faros/credentials.json'))['api_key'])")
AGENT_ID=$(python3 -c "import json; print(json.load(open('$HOME/.faros/credentials.json'))['agent_id'])")
AUTH_AGENT="Authorization: Bearer $API_KEY"

STALE=$(curl -s -X POST "http://localhost:8000/api/agents/$AGENT_ID/commands" \
  -H 'Content-Type: application/json' -H "$AUTH_OP" \
  -d '{"type": "ModelDeploy", "payload": {"group": "drivetrain", "onnx_url": "http://example.com/model.onnx", "artifact_url": "http://example.com/artifact.yaml"}}')
echo "QUEUED: $STALE"
STALE_ID=$(echo "$STALE" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

sleep 2

curl -s -X GET "http://localhost:8000/api/agents/commands" \
  -H "$AUTH_AGENT" | python3 -m json.tool
```

**Expected:** Poll returns `[]` — the command was expired, not delivered.

### Verify expired status in operator view

```bash
curl -s "http://localhost:8000/api/agents/$AGENT_ID/commands/$STALE_ID" \
  -H "$AUTH_OP" | python3 -m json.tool
```

**Expected:** `status: "expired"`, `delivered_at` is set (records when the server expired it).

---

## Test 8: Command TTL — Ack on Expired Command (expect 409)

Try to ack the expired command from Test 7:

```bash
curl -s -w "\nHTTP %{http_code}\n" \
  -X POST "http://localhost:8000/api/agents/commands/$STALE_ID/ack" \
  -H 'Content-Type: application/json' -H "$AUTH_AGENT" \
  -d '{"success": true, "message": "too late"}'
```

**Expected:** HTTP 409

---

## Test 9: Command TTL — Output on Expired Command (expect 409)

Try to append output to the expired command from Test 7:

```bash
curl -s -w "\nHTTP %{http_code}\n" \
  -X POST "http://localhost:8000/api/agents/commands/$STALE_ID/output" \
  -H 'Content-Type: application/json' -H "$AUTH_AGENT" \
  -d '{"output": "too late"}'
```

**Expected:** HTTP 409

---

## Test 10: Command TTL — Mixed Batch (fresh + stale)

With TTL=1 still active, queue two commands, wait, then queue a third. Only the third should be delivered.

```bash
curl -s -o /dev/null -X POST "http://localhost:8000/api/agents/$AGENT_ID/commands" \
  -H 'Content-Type: application/json' -H "$AUTH_OP" \
  -d '{"type": "Discover"}'

curl -s -o /dev/null -X POST "http://localhost:8000/api/agents/$AGENT_ID/commands" \
  -H 'Content-Type: application/json' -H "$AUTH_OP" \
  -d '{"type": "Validate"}'

sleep 2

curl -s -X POST "http://localhost:8000/api/agents/$AGENT_ID/commands" \
  -H 'Content-Type: application/json' -H "$AUTH_OP" \
  -d '{"type": "Status"}'

curl -s -X GET "http://localhost:8000/api/agents/commands" \
  -H "$AUTH_AGENT" | python3 -m json.tool
```

**Expected:** Poll returns only the `Status` command. Operator listing shows `Discover` and `Validate` as `expired`, `Status` as `in_progress`:

```bash
curl -s "http://localhost:8000/api/agents/$AGENT_ID/commands" \
  -H "$AUTH_OP" | python3 -m json.tool
```

---

## Test 11: Command TTL — Expired Visible in Filtered List

```bash
curl -s "http://localhost:8000/api/agents/$AGENT_ID/commands?status=expired" \
  -H "$AUTH_OP" | python3 -m json.tool
```

**Expected:** Returns all expired commands (from Tests 7 and 10). Each has `status: "expired"` and `delivered_at` set.

**Restart the server with default TTL before continuing:**

```bash
.venv/bin/faros-server run
```

---

## Test 12: Heartbeat (Sanity Check)

```bash
curl -s -X POST "http://localhost:8000/api/agents/heartbeat" \
  -H 'Content-Type: application/json' -H "$AUTH_AGENT" \
  -d '{"uptime_s": 120, "cpu_pct": 3.2}'
```

---

## Test 13: Logout Command (Do This LAST)

The agent handles Logout automatically — it acks the command, revokes its
server API key, removes local credentials, and shuts down. This is the same
behaviour as `faros-agent logout` from the CLI.

```bash
Q=$(curl -s -X POST "http://localhost:8000/api/agents/$AGENT_ID/commands" \
  -H 'Content-Type: application/json' -H "$AUTH_OP" \
  -d '{"type": "Logout"}')
echo "QUEUED: $Q"
CID=$(echo "$Q" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

sleep 3

curl -s "http://localhost:8000/api/agents/$AGENT_ID/commands/$CID" \
  -H "$AUTH_OP" | python3 -m json.tool
```

**Expected:** `status: "acked"`, agent process exits.

### Verify key is revoked (expect 401)

```bash
curl -s -w "HTTP %{http_code}\n" \
  -X GET "http://localhost:8000/api/agents/commands" -H "$AUTH_AGENT"
```

**Expected:** HTTP 401 — the agent revoked its own key during logout.

---

## Expected Results Summary

| Test | Endpoint | Expected |
|------|----------|----------|
| 1 | TestLongRunning e2e | Output streams automatically, acked with success |
| 1 | GET command mid-flight | partial output visible, status in_progress |
| 1 | GET command after ack | all output + result preserved |
| 2 | POST /output (pending) | 409 |
| 3 | All command types | Agent handles all, status=acked |
| 5 | No auth | 401 |
| 5 | Nonexistent | 404 |
| 5 | Empty output | 400 |
| 5 | Acked command | 409 |
| 6 | Fresh command poll | 200, command delivered |
| 7 | Stale command poll (TTL=1) | 200, `[]` returned, status expired |
| 8 | Ack expired command | 409 |
| 9 | Output on expired command | 409 |
| 10 | Mixed batch (TTL=1) | Only fresh command delivered |
| 11 | List expired commands | All expired with delivered_at set |
| 13 | Logout command | acked, agent exits, key revoked (401) |
