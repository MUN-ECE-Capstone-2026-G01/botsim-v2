# TODO — botsim-v2 Implementation Steps

Work through these steps in order. Each step is small enough to implement and test independently.

---

## Phase 1 — Refactor Robot Code

**Goal:** Clean separation of concerns in the Pi-side code. Robot still works standalone after this phase (same behavior as today, just reorganized).

- [x] **1.1** Create `robot/` directory in `botsim-v2`
- [x] **1.2** Update `robot/localization.py` to use the threaded `LighthouseSensor` class pattern (from new `decodeV2pos.py`):
  - Keep low-level classes: `SweepData`, `SweepBlock`, `Angles`, `BaseStation`, `PulseProcessor`, `calculateAE()`, `ts_sub()`, `ts_add()`, `PERIODS`
  - Move `get_yaw_from_rvec()` here (it belongs with pose data, not motor control)
  - Add `LighthouseSensor(source_path)` class:
    - `__init__`: stores path, initializes `latest_x/y/yaw`, `has_new_data`, `lock`, `running`
    - `run_continuous_reading()`: blocking sync/read loop (run in `daemon=True` thread)
    - `_update_pose(angles_obj)`: calls solvePnP, updates state under lock; note `tvec[2]` → Y
    - `check_new_data()` → `bool` (thread-safe)
    - `get_latest_reading()` → `(x, y, yaw)` (thread-safe, clears `has_new_data`)
  - Remove the old top-level `calculate_coordinates()` function
- [x] **1.3** Update `robot/motor_control.py` — align with new `drive.py` reference:
  - Change `SERIAL_PORT` to `'/dev/ttyS0'` (motors) — **not** `/dev/ttyAMA2` (that's the lighthouse port)
  - Remove `get_yaw_from_rvec()` (now lives in `localization.py`)
  - Add `go_to_position(current_x, current_y, current_theta)` → `(v, w)` (proportional control; advances `current_target_idx` on arrival)
  - Add `pure_pursuit(current_x, current_y, current_theta)` → `(v, w)` (lookahead path follower along `TARGET_LIST`)
  - Keep `stop_motors()` sending `0.00,0.00\n`
  - Keep gains (`Kv`, `Kh`) and safety caps (`MAX_V`, `MAX_W`, `STOP_DIST`) as module-level constants
  - Add `LOOP_FREQ = 20.0`, `DT = 1.0 / LOOP_FREQ` as constants
- [x] **1.3b** Create `robot/ekf.py` — Extended Kalman Filter:
  - `ExtendedKalmanFilter(initial_x, initial_y, initial_yaw)` class
  - `predict(v, w, dt)`: differential-drive kinematic update + covariance propagation via Jacobian `F`
  - `update(meas_x, meas_y, meas_yaw)`: lighthouse correction (identity `H`; normalize yaw residual)
  - `get_state()` → `(x, y, yaw)`
  - Tunable: `Q` (process noise), `R` (measurement noise — lighthouse is accurate, keep small)
- [x] **1.4** Update `robot/agent.py` — fixed-rate 20 Hz control loop:
  - Start `LighthouseSensor` in a `daemon=True` background thread
  - Initialize `ExtendedKalmanFilter`
  - Track `current_v, current_w` across iterations (needed for EKF predict)
  - Main loop: `ekf.predict(v, w, DT)` → conditional `ekf.update()` if sensor has new data → `ekf.get_state()` → `pure_pursuit()` → send serial command → `time.sleep(remaining)`
  - Default target: first entry in `TARGET_LIST` (e.g. `(0, 1.7)`)
  - Accepts lighthouse serial port as CLI argument
- [x] **1.5** Update `deck.sh` to call `robot/agent.py` instead of `Lighthouse-Deck/tools/decodeV2pos.py`
  - Note: shape-deployer eliminated deck.sh entirely and inlines the reboot/flash/start commands via SSH. We may do the same in Phase 3 (fleet_manager.py can issue the three commands directly).
- [ ] **1.6** Smoke test: deploy `robot/` manually to one Pi and verify it drives to the hardcoded target as before

---

## Phase 2 — Robot Network Layer + Algorithms

**Goal:** Each Pi can connect to the host broker, receive algorithm commands, and run algorithms locally. Requires host broker to be running (Phase 3), but broker_client should degrade gracefully if broker is absent.

- [ ] **2.1** Create `fleet.yaml` at repo root with placeholder values:
  - `broker_host`, `broker_port` (default 8765), `broker_timeout` (default 5)
  - List of robots: `id`, `host`, `user`
- [ ] **2.2** Create `robot/config.py` — reads robot ID and broker connection info from a local config file on the Pi (a copy of `fleet.yaml` deployed there, or a small `robot_config.yaml`)
- [ ] **2.3** Create `robot/algorithms/base.py` — abstract `SwarmAlgorithm` class:
  ```python
  def compute_target(self, my_id: str, all_positions: dict) -> tuple[float, float]
  ```
- [ ] **2.4** Create `robot/algorithms/idle.py` — returns `None` (agent calls `stop_motors()` when target is `None`)
- [ ] **2.5** Create `robot/algorithms/pentagon.py`:
  - Compute centroid of all robot positions in `all_positions`
  - Place 5 vertices evenly around centroid at a fixed radius (configurable, e.g. 0.5m)
  - Assign robots to vertices using `scipy.optimize.linear_sum_assignment` (min total distance)
  - Return the vertex assigned to `my_id`
- [ ] **2.6** Create `robot/broker_client.py` — async WebSocket client (runs in background thread):
  - Connects to `ws://<broker_host>:<broker_port>/ws/robot`
  - On connect: sends `{"type": "hello", "id": "<robot_id>"}`
  - Publishes position: `{"type": "position", "id": ..., "x": ..., "y": ..., "theta": ...}`
  - Receives `{"type": "state", "positions": {...}}` → updates shared state
  - Receives `{"type": "algorithm", "name": "..."}` → signals algorithm change to agent
  - Tracks `last_contact` timestamp; exposes `is_timed_out()` method
  - Attempts reconnection in background if connection drops
- [ ] **2.7** Update `robot/agent.py` to use broker_client and algorithms:
  - Start `broker_client` in a background thread on startup
  - Default algorithm: `idle`
  - Each localization loop iteration:
    - Publish position via broker_client
    - If `broker_client.is_timed_out()` → call `stop_motors()`, skip drive
    - If broker_client has a new algorithm → dynamically load it from `algorithms/`
    - Get `all_positions` from broker_client shared state
    - Call `current_algorithm.compute_target(my_id, all_positions)` → target
    - If target is `None` → `stop_motors()`, else `drive_to_target(target, ...)`
- [ ] **2.8** Create `requirements-robot.txt` (scipy, websockets, pyserial, opencv-python, numpy; no new deps for EKF — uses only numpy/math)
- [ ] **2.9** Test broker_client in isolation: run agent with no broker running → verify robot stays idle and does not crash

---

## Phase 3 — Host Backend

**Goal:** FastAPI server that acts as broker, fleet manager, and REST API.

- [ ] **3.1** Create `host/broker.py` — WebSocket connection manager:
  - Maintains dict of connected Pi clients (`robot_id → websocket`)
  - Maintains `positions` dict (latest position per robot)
  - On position message from Pi: update `positions`, broadcast updated state to all Pis and all UI clients
  - On algorithm command (from UI endpoint): broadcast `{"type": "algorithm", "name": "..."}` to all Pis
  - On Pi disconnect: mark robot offline in state
- [ ] **3.2** Create `host/fleet_manager.py` using `asyncssh`:
  - Load fleet from `fleet.yaml`
  - `deploy(robot_id)` — rsync `robot/` directory to Pi (to `~/botsim/`)
  - `start(robot_id)` — SSH: run `deck.sh` in background, capture output
  - `stop(robot_id)` — SSH: `pkill -f agent.py`
  - `deploy_all()`, `start_all()`, `stop_all()` — run concurrently with `asyncio.gather`
  - SSH credentials: read from `.env` file (password) or use key auth if available
- [ ] **3.3** Create `host/main.py` — FastAPI app:
  - Mount `web/` as static files
  - Include all REST endpoints (see PLAN.md for full list)
  - `GET /robots` → returns fleet status from broker state
  - `POST /robots/{id}/deploy|start|stop` → calls fleet_manager
  - `POST /robots/deploy_all|start_all|stop_all` → calls fleet_manager
  - `POST /algorithm` → calls broker to broadcast algorithm switch
  - `WebSocket /ws/robot` → Pi agents connect here (handled by broker)
  - `WebSocket /ws/ui` → browser connects here (broker pushes updates)
- [ ] **3.4** Create `requirements-host.txt` (fastapi, uvicorn, asyncssh, pyyaml, python-dotenv, websockets)
- [ ] **3.5** Test backend standalone: start FastAPI server, manually connect a WebSocket client, verify broker fans out messages correctly

---

## Phase 4 — Web UI

**Goal:** Single-page browser interface for fleet management and algorithm control.

- [ ] **4.1** Create `web/index.html` — page structure:
  - Fleet panel (robot table)
  - Algorithm panel (dropdown + Run button)
  - Log panel (scrolling text output)
  - Map panel (`<canvas>` element for 2D live visualization)
- [ ] **4.2** Create `web/app.js`:
  - On load: `GET /robots` to populate fleet table
  - Open WebSocket to `/ws/ui` for live updates
  - On WS message: update robot rows (status, position)
  - Wire up per-robot buttons (deploy, start, stop)
  - Wire up group buttons (Deploy All, Start All, Stop All)
  - Wire up algorithm dropdown + Run button → `POST /algorithm`
  - Append status messages to log panel
  - On WS position message: redraw map canvas (robot dots + formation target markers)
- [ ] **4.3** Create `web/style.css` — minimal clean styling:
  - Online/offline color badges per robot
  - Responsive layout
- [ ] **4.4** Implement map canvas in `web/app.js`:
  - `<canvas>` with a fixed world-space viewport (e.g. ±2 m from origin)
  - Each robot drawn as a labeled dot; heading shown as a short line
  - Formation target vertices drawn as hollow circles (if algorithm is active)
  - Redraws on every incoming WS state message (~20 Hz)
- [ ] **4.5** Test UI in browser: verify fleet table updates live, buttons trigger correct API calls, log panel shows output, map shows robot positions moving in real time

---

## Phase 5 — Integration & Setup

**Goal:** End-to-end working system; documented setup process.

- [ ] **5.1** Create `.env.example` with SSH password placeholder (actual `.env` is gitignored)
- [ ] **5.2** Add `.gitignore` (`.env`, `__pycache__`, `*.pyc`, `venv/`)
- [ ] **5.3** Update `README.md`:
  - Prerequisites (Python version, required packages)
  - One-time SSH key setup instructions for each Pi
  - How to set `broker_host` in `fleet.yaml`
  - How to start the host server (`uvicorn host.main:app`)
  - How to deploy and start robots from the UI
- [ ] **5.4** End-to-end test with 1 robot:
  - Deploy from UI → Start from UI → verify robot localizes and stays idle
  - Select pentagon algorithm from UI → verify robot drives toward its assigned vertex
- [ ] **5.5** End-to-end test with 2+ robots:
  - Verify positions of all robots appear in UI
  - Verify pentagon assignment works (nearest vertex)
  - Verify broker timeout: kill host server → robots should stop after 5s

---

## Phase 6 — Additional Algorithms (ongoing)

- [ ] **6.1** `robot/algorithms/rendezvous.py` — all robots converge to centroid of current positions
- [ ] **6.2** `robot/algorithms/foraging.py` — TBD based on requirements
- [ ] **6.3** Add algorithm radius/parameter configuration to `fleet.yaml` or passed via `POST /algorithm` body

---

## Future (not scheduled)

- [ ] Direct keyboard teleoperation of a single robot from host
- [ ] "Restart agent" (no bootloader re-flash) button in UI
- [ ] Per-robot gain tuning from UI
