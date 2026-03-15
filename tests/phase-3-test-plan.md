# Phase 3 Test Plan — Host Backend

Manual test plan. Run the FastAPI server on your laptop; Pi must be on the same WiFi.

---

## Prerequisites

1. Create `.env` from `.env.example` and set `SSH_PASSWORD`.
2. Ensure `fleet.yaml` has the correct `broker_host` (your laptop's IP).
3. Install host deps: `uv sync`
4. Start the server on port **8765** — this must match `broker_port` in `fleet.yaml` so the Pi can connect:

   ```bash
   uv run uvicorn host.main:app --host 0.0.0.0 --port 8765
   ```

   Expected: uvicorn starts, no import errors.

   > **Port note:** `fleet.yaml` sets `broker_port: 8765`. The Pi connects to
   > `ws://<broker_host>:<broker_port>/ws/robot`, so uvicorn must listen on the
   > same port. If you change this, update both `fleet.yaml` and the uvicorn command.

---

## Test 3.1 — GET /robots (fleet status)

```bash
curl http://localhost:8765/robots
```

Expected response:

```json
[
  {"id": "civr-1", "host": "civr-1.local", "online": false, "position": null}
]
```

- `online` is `false` because no robot has connected yet.
- If this fails, the server is not running or is on the wrong port.

---

## Test 3.2 — UI WebSocket receives log messages

Open a WebSocket to `ws://localhost:8765/ws/ui` using a browser console snippet.

> **Important:** Run this from an `about:blank` tab, not from a regular website.
> Most pages have a Content Security Policy that blocks `ws://` connections and will
> give a `NS_ERROR_CONTENT_BLOCKED` error. `about:blank` has no CSP restrictions.

1. Open a new browser tab and navigate to `about:blank`
2. Open DevTools (F12) → Console
3. Paste:

```js
const ws = new WebSocket("ws://localhost:8765/ws/ui");
ws.onmessage = e => console.log(e.data);
```

Expected: no errors; `ws.readyState` returns `1` (OPEN) after a moment.

Keep this open for the remaining tests — log messages will appear here.

---

## Test 3.3 — Pi agent connects (broker /ws/robot)

**Before running the agent, verify the server is reachable from the Pi:**

```bash
# On the Pi:
curl http://192.168.78.83:8765/robots
```

Expected: same JSON as Test 3.1. If this fails, the firewall on your laptop may be
blocking port 8765 — check Windows Firewall and allow uvicorn through.

**Then start the agent on the Pi:**

```bash
python3 ~/botsim/robot/agent.py /dev/ttyAMA2
```

Expected on the **Pi terminal** (within a few seconds):

```
[broker] Connected to ws://192.168.78.83:8765/ws/robot
```

Expected on the **server terminal**:

```
INFO:     connection open
```

Expected on the **UI WebSocket** (from Test 3.2):

```json
{"type": "log", "message": "[civr-1] connected"}
```

Expected from `GET /robots`:

```json
[{"id": "civr-1", "online": true, "position": null, ...}]
```

---

## Test 3.4 — Position updates fan out

While the Pi agent is running, position updates should broadcast.

Check the UI WebSocket — you should see messages like:

```json
{"type": "state", "positions": {"civr-1": {"x": 1.23, "y": 0.45, "theta": 0.1, "last_seen": ...}}}
```

Also check `GET /robots` — the `position` field should now be populated.

---

## Test 3.5 — Algorithm broadcast

```bash
curl -X POST http://localhost:8765/algorithm -H "Content-Type: application/json" -d '{"name": "pentagon"}'
```

Expected:

- Returns `{"ok": true}`
- Pi agent log shows: `[broker] Algorithm → pentagon`
- UI WebSocket shows: `{"type": "log", "message": "Algorithm → pentagon"}`

---

## Test 3.6 — Robot disconnect

Stop the Pi agent (Ctrl+C on the Pi).

Expected on the **UI WebSocket**:

```json
{"type": "log", "message": "[civr-1] disconnected"}
```

Expected from `GET /robots`:

```json
[{"id": "civr-1", "online": false, ...}]
```

The `position` field should still show the last known position (broker retains it).

---

## Test 3.7 — Deploy

```bash
curl -X POST http://localhost:8765/robots/civr-1/deploy
```

Expected:

- Returns `{"ok": true, "message": "Deploy complete"}`
- On the Pi, verify files arrived:

  ```bash
  ls ~/botsim/robot/
  cat ~/botsim/fleet.yaml
  ```

  Should see: `agent.py`, `broker_client.py`, `config.py`, `ekf.py`, `localization.py`, `motor_control.py`, `algorithms/`

---

## Test 3.8 — Stop

```bash
curl -X POST http://localhost:8765/robots/civr-1/stop
```

Expected (agent running): `{"ok": true, "message": "Stopped"}`
Expected (agent not running): `{"ok": true, "message": "agent.py was not running"}`

Verify on Pi: `pgrep -a python3` — no `agent.py` process.

---

## Test 3.9 — Start

```bash
curl -X POST http://localhost:8765/robots/civr-1/start
```

Expected:

- Blocks for ~10–15s while lighthouse FPGA is flashed
- Returns `{"ok": true, "message": "<flash output>"}`
- Agent starts as background daemon on the Pi
- Verify: `pgrep -a python3` shows `agent.py /dev/ttyAMA2`
- Verify after a few seconds: `tail /tmp/agent.log` on the Pi has output
- Verify connection: run `curl http://localhost:8765/robots` and check `"online": true`

> **Note:** The UI WebSocket from Test 3.2 may have dropped during the ~15s flash delay.
> If the broker shows the robot online but you see nothing in the browser console,
> re-open the WebSocket:
> ```js
> const ws = new WebSocket("ws://localhost:8765/ws/ui");
> ws.onmessage = e => console.log(e.data);
> ```

---

## Test 3.10 — deploy_all / start_all / stop_all

```bash
curl -X POST http://localhost:8765/robots/deploy_all
curl -X POST http://localhost:8765/robots/start_all
curl -X POST http://localhost:8765/robots/stop_all
```

Expected: JSON array with one entry per robot, each with `ok` and `message`.
For a single-robot fleet this behaves identically to the per-robot endpoints.

---

## Test 3.11 — Unknown robot ID

```bash
curl -X POST http://localhost:8765/robots/civr-99/start
```

Expected: `{"ok": false, "message": "Unknown robot: civr-99"}`

---

## Notes

- `start` runs the full lighthouse flash sequence before launching the agent. This takes ~10–15s.
- `deploy` uploads `robot/` and `fleet.yaml` but does NOT restart the agent. Run `stop` then `start` after deploying new code.
- Logs broadcast to `/ws/ui` in real time — useful for the Phase 4 UI log panel.
