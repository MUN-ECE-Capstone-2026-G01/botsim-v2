# botsim-v2 — Swarm Robotics Platform Plan

## Overview

A web-based platform for orchestrating a fleet of differential-drive robots (Raspberry Pi + ESP32) using Steam Lighthouse-based localization. The host computer deploys code, starts/stops robots, and selects swarm algorithms. Algorithms run **on each Pi**; the host acts as a position broker and fleet manager.

---

## Hardware Context

- **Robot**: Differential drive, Raspberry Pi + ESP32 (motor driver via UART)
- **Localization**: Steam Lighthouse deck (infrared), connected to Pi via `/dev/ttyAMA2`
- **Fleet size**: 5–6 robots
- **Hostnames**: `visor@civr-1.local`, `visor@civr-2.local`, etc. (configurable)
- **Network**: All devices on the same WiFi; host connects to Pis via mDNS/SSH

---

## Architecture

```
[Browser] <── REST/WebSocket ──> [Host: FastAPI]
                                       │
                             ┌─────────┴──────────┐
                             │ SSH (deploy/start)  │ WebSocket broker (/ws/robot)
                             │                     │
                        [Pi-1 ... Pi-N]      positions in ↑  ↓ global state + algorithm
                        agent.py
                             │
                    ┌────────┴────────┐
               localization.py   motor_control.py
                    │                 │
              [Lighthouse FPGA]   [ESP32 / UART]
```

### Host responsibilities (runtime)
1. Receive position updates from all Pis → maintain global state
2. Broadcast global state back to all Pis (so each robot knows all positions)
3. Push algorithm selection commands to all Pis
4. SSH-based deploy, start, stop
5. Serve the web UI

### Pi responsibilities (runtime)
1. Localize via lighthouse, publish `{id, x, y, theta}` to host broker
2. Receive `{all_positions}` + `{algorithm: "pentagon"}` from host broker
3. Run the selected algorithm locally: `algorithm.compute_target(my_id, all_positions)` → `(tx, ty)`
4. Execute motor control toward that target

---

## Repository Structure

```
botsim-v2/
├── PLAN.md
├── TODO.md
├── fleet.yaml                    # Robot fleet configuration
├── requirements-host.txt         # Host Python dependencies
├── requirements-robot.txt        # Pi Python dependencies (deployed with robot/)
│
├── host/                         # Runs on the host laptop
│   ├── main.py                   # FastAPI app: web UI server + broker endpoints
│   ├── fleet_manager.py          # SSH: deploy, start, stop per robot
│   └── broker.py                 # WebSocket broker: aggregates positions, fans out state
│
├── web/                          # Browser UI (served by FastAPI)
│   ├── index.html
│   ├── app.js
│   └── style.css
│
└── robot/                        # Deployed to each Pi via rsync/SCP
    ├── agent.py                  # Main entry point (replaces decodeV2pos.py as entry)
    ├── localization.py           # All lighthouse logic (extracted from decodeV2pos.py)
    ├── motor_control.py          # drive_to_target, serial setup (from decodeV2pos.py)
    ├── broker_client.py          # WebSocket client: publish position, receive state
    ├── config.py                 # Reads robot ID and broker address from config file
    └── algorithms/
        ├── base.py               # Abstract base class: compute_target(my_id, all_positions)
        ├── idle.py               # Default: stop motors, hold position
        └── pentagon.py           # Pentagon formation with nearest-vertex assignment
```

---

## Key Design Decisions

### Broker connection timeout
- Each Pi keeps a `last_contact` timestamp
- If the broker is unreachable, the robot continues toward its last known target
- If disconnected for more than `broker_timeout` seconds (default: 5, set in `fleet.yaml`), the robot switches to `idle` (stops motors)
- The Pi reconnects automatically in the background

### Algorithm startup state
- On startup, robots always begin in `idle` (stopped) regardless of what was running before
- The host UI sends an explicit algorithm selection to start movement

### Vertex/target assignment in algorithms
- Algorithms compute all targets (e.g., pentagon vertices) from the centroid of current robot positions
- Assignment uses minimum total distance (scipy `linear_sum_assignment`)
- Each robot independently computes the same assignment deterministically and selects its own target by `my_id`
- No inter-robot communication required beyond what the broker already provides

### Bootloader / lighthouse FPGA init
- `deck.sh` runs the full sequence on every `Start`:
  1. Reboot lighthouse FPGA via `reboot.py`
  2. Flash `lighthouse.bin` via `uart_bootloader.py`
  3. Launch `agent.py`
- This is safe to run every session start; takes a few extra seconds
- `Stop` from the UI kills only the `agent.py` process (FPGA stays loaded)
- A future "Restart Agent" action (no bootloader re-flash) can be added when needed

### SSH authentication
- Initially supports password-based SSH (password stored in local `.env`, gitignored)
- Recommend setting up key-based auth for all Pis as a one-time setup step (instructions in README)
- `fleet_manager.py` uses `asyncssh` which supports both modes

---

## Fleet Configuration (`fleet.yaml`)

```yaml
broker_host: "192.168.x.x"    # Host laptop IP — set before deploying
broker_port: 8765
broker_timeout: 5              # Seconds before robot stops if broker unreachable

robots:
  - id: civr-1
    host: civr-1.local
    user: visor
  - id: civr-2
    host: civr-2.local
    user: visor
  # ... up to civr-6
```

---

## Component Details

### `robot/localization.py`
Pure extraction of lighthouse logic from `decodeV2pos.py`:
- `SweepData`, `SweepBlock`, `Angles`, `BaseStation`, `PulseProcessor`
- `calculate_coordinates_using_p2p()` → returns `(position, rotation_vec)` instead of calling `drive_to_target` directly

### `robot/motor_control.py`
- Serial setup (`/dev/ttyAMA2`, 115200 baud)
- `drive_to_target(target_x, target_y, position, rotation_vec)` — unchanged logic, target passed as parameter
- `stop_motors()` — sends `0,0\n`
- Gains (`Kv`, `Kh`) and safety caps (`MAX_V`, `MAX_W`) remain unchanged

### `robot/broker_client.py`
- Async WebSocket client
- Sends: `{"type": "position", "id": "civr-1", "x": 1.2, "y": 0.5, "theta": 0.3}`
- Receives:
  - `{"type": "state", "positions": {"civr-1": {...}, "civr-2": {...}}}` — global robot state
  - `{"type": "algorithm", "name": "pentagon"}` — algorithm switch
- Tracks `last_contact` timestamp; signals timeout to agent

### `robot/agent.py`
Main loop (simplified):
```
load config (robot ID, broker address)
start broker_client in background thread
current_algorithm = idle
current_target = None

loop (lighthouse serial):
    position, rotation_vec = localization.process_frame(frame)
    broker_client.publish_position(position)

    if broker_client.timed_out():
        stop_motors()
        continue

    if broker_client.has_new_algorithm():
        current_algorithm = load_algorithm(new_name)

    all_positions = broker_client.get_latest_state()
    target = current_algorithm.compute_target(my_id, all_positions)
    motor_control.drive_to_target(target, position, rotation_vec)
```

### `robot/algorithms/base.py`
```python
class SwarmAlgorithm:
    def compute_target(self, my_id: str, all_positions: dict) -> tuple[float, float]:
        raise NotImplementedError
```

### `robot/algorithms/pentagon.py`
1. Compute centroid of all known robot positions
2. Place 5 pentagon vertices evenly around centroid at a fixed radius
3. Use `scipy.optimize.linear_sum_assignment` to assign robots → vertices (min total distance)
4. Return the vertex assigned to `my_id`

### `host/broker.py`
- Manages all active Pi WebSocket connections
- On position message from Pi: update global `positions` dict, broadcast updated state to all Pis and to UI clients
- On algorithm command from UI: broadcast `{"type": "algorithm", "name": "..."}` to all Pis

### `host/fleet_manager.py`
- `deploy(robot_id)` — rsync `robot/` directory to Pi home folder
- `start(robot_id)` — SSH: run `deck.sh` (full init + agent)
- `stop(robot_id)` — SSH: kill `agent.py` process
- `deploy_all()`, `start_all()`, `stop_all()` — parallel across fleet

### `host/main.py` — FastAPI endpoints
| Method | Path | Description |
|---|---|---|
| GET | `/robots` | Fleet status (online/offline, last position) |
| POST | `/robots/{id}/deploy` | Deploy `robot/` to one robot |
| POST | `/robots/{id}/start` | Full start (bootloader + agent) |
| POST | `/robots/{id}/stop` | Stop agent process |
| POST | `/robots/deploy_all` | Deploy to all robots |
| POST | `/robots/start_all` | Start all robots |
| POST | `/robots/stop_all` | Stop all robots |
| POST | `/algorithm` | Switch algorithm: `{"name": "pentagon"}` |
| WS | `/ws/robot` | Pi agents connect here |
| WS | `/ws/ui` | Browser connects here for live updates |

### `web/` — UI panels
- **Fleet panel**: one row per robot — hostname, online/offline badge, last seen position, per-robot deploy/start/stop buttons; group action buttons (Deploy All, Start All, Stop All)
- **Algorithm panel**: dropdown of available algorithms, Run button
- **Log panel**: streaming status/output from fleet manager and broker
- *(Later)* 2D canvas visualization of robot positions

---

## Implementation Phases

| Phase | Work |
|---|---|
| **1** | Refactor `decodeV2pos.py` → `localization.py` + `motor_control.py` + `agent.py`; update `deck.sh` to call `agent.py` |
| **2** | Add `broker_client.py` with timeout logic; add `algorithms/` (`idle`, `pentagon`); full robot-side stack |
| **3** | Build `host/broker.py` + `host/fleet_manager.py` + `host/main.py` (FastAPI backend) |
| **4** | Build `web/` UI (fleet panel, algorithm panel, log panel) |
| **5** | `fleet.yaml`, `requirements-*.txt`, SSH key setup docs, end-to-end test |
| **6** | Additional algorithms (foraging, etc.) as needed |

---

## Future / Out of Scope for Now
- Live 2D position visualization (map view)
- Direct keyboard teleoperation of a single robot from host
- Per-robot gain tuning from UI
- Monitoring / metrics dashboard
