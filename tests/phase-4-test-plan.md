# Phase 4 Test Plan — Web UI

Manual test plan. Server must be running (`uv run uvicorn host.main:app --host 0.0.0.0 --port 8765`).

Open the UI in a browser: `http://localhost:8765/web/index.html`

---

## Test 4.1 — Page loads

Navigate to `http://localhost:8765/web/index.html`.

Expected:

- Page renders with four sections: Fleet, Algorithm, Map, Log
- Header shows a blue "connected" badge within a second
- Log panel shows: `Connected to broker`
- Fleet table shows one row per robot with "offline" badges (if no Pi connected)

---

## Test 4.2 — Fleet table populates on Pi connect

Start the agent on the Pi:

```bash
python3 ~/botsim/robot/agent.py /dev/ttyAMA2
```

Expected:

- The robot's row in the fleet table switches from "offline" (red) to "online" (green)
- Log panel shows: `[civr-1] connected`
- Within a few seconds, the Position column shows live coordinates (e.g. `1.23, 0.45, 0.10`)
- Map canvas shows the robot as a colored dot with a heading line

---

## Test 4.3 — Map updates live

While the Pi agent is running, watch the map canvas.

Expected:

- Robot dot moves as the robot moves
- Heading line rotates to match the robot's yaw
- Grid lines and axes are visible

---

## Test 4.4 — Algorithm panel

With the Pi connected, select "pentagon" from the dropdown and click Run.

Expected:

- Log shows: `Algorithm set to: pentagon`
- Log shows: `Algorithm → pentagon`
- The Pi agent log shows: `[broker] Algorithm → pentagon`
- On the map, 5 hollow circles appear around the centroid of current robot positions (pentagon formation targets)
- `algo-active` label updates to show "pentagon"

Select "idle" and click Run.

Expected:

- Formation target circles disappear from the map
- Pi agent stops driving (if it was moving)

---

## Test 4.5 — Per-robot Deploy button

Click the Deploy button for civr-1 in the fleet table.

Expected:

- Log shows: `[civr-1] deploy…`
- After a few seconds: `[civr-1] deploy: Deploy complete` (green)

---

## Test 4.6 — Per-robot Stop button

With the agent running, click Stop for civr-1.

Expected:

- Log shows: `[civr-1] stop: Stopped` (green)
- Fleet table row switches to "offline"
- Map dot disappears (or stays at last position until next state update)

---

## Test 4.7 — Per-robot Start button

With the agent stopped, click Start for civr-1.

Expected:

- Log shows: `[civr-1] start…`
- Button is NOT disabled during the wait (the request runs in the background from the browser)
- After ~15s: `[civr-1] start: <flash output>` (green)
- Robot reconnects → row goes back to "online"

---

## Test 4.8 — Group action buttons

Click **Stop All**.

Expected:

- Log shows one entry per robot with stop result
- All robots go offline

Click **Start All**.

Expected:

- All robots flash and reconnect (takes ~15s)

Click **Deploy All**.

Expected:

- All robots receive updated files

---

## Test 4.9 — WebSocket auto-reconnect

Stop the uvicorn server (Ctrl+C on the server terminal).

Expected:

- Header badge switches to "disconnected" (red)
- Log shows: `Disconnected — reconnecting in 3s…`

Restart the server.

Expected:

- Badge switches back to "connected" (blue) within 3s
- Log shows: `Connected to broker`

---

## Test 4.10 — Log panel scroll and cap

Trigger many log messages (e.g. deploy several times).

Expected:

- Log panel auto-scrolls to the latest entry
- Panel does not grow beyond 200 lines (old entries are removed)

---

## Notes

- The UI is served at `/web/index.html`. There is no redirect from `/` yet (Phase 5).
- Start/Stop/Deploy buttons do not disable during long operations — feedback comes via the log panel.
- Pentagon formation targets on the map are computed client-side from the centroid of currently-online robots, using the same 0.5 m radius as `pentagon.py`.
