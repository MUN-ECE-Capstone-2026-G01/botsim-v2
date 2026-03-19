# botsim-v2 — Setup & Run Guide

## Prerequisites (once per host laptop)

```bash
# Install uv if not already installed
pip install uv

# From repo root — installs all host dependencies
uv sync

# Create .env from template and set SSH password
cp .env.example .env
# Edit .env:  SSH_PASSWORD=<password for visor user on all Pis>
```

---

## Every session

### 1 — Update broker IP in `fleet.yaml`

Find your laptop's IP on the shared WiFi:

```bash
# Windows
ipconfig    # look for IPv4 Address under your WiFi adapter (e.g. 192.168.X.X)
```

Edit `fleet.yaml`:

```yaml
broker_host: "192.168.X.X"   # ← your laptop IP
```

> **Note:** `broker_port: 8765` — this must match the port you start the server on (step 2).

---

### 2 — Start the host server

```bash
# From repo root
uv run uvicorn host.main:app --host 0.0.0.0 --port 8765
```

Open **`http://localhost:8765`** in your browser.
You should see the fleet UI with both robots showing as offline.

---

### 3 — Deploy code to robots

In the UI, click **Deploy All** (or per-robot **Deploy**).

This uploads `robot/` + `fleet.yaml` to `~/botsim/` on each Pi via SFTP.

Watch the log panel — expect:
```
[civr-white] deploy: ok
[civr-blue] deploy: ok
```

> If you see an auth error, check `SSH_PASSWORD` in `.env`.
> If you see a connection error, check the Pi is on the same WiFi and responds to `ping civr-white.local`.

---

### 4 — Start robots

Click **Start All** (or per-robot **Start**).

This SSHes into each Pi and:
1. Reboots the lighthouse FPGA
2. Flashes `lighthouse.bin` via UART bootloader
3. Launches `agent.py` as a background daemon

This takes ~15–20 s per robot. Watch the log panel — expect:
```
[civr-white] start: ok
[civr-blue] start: ok
[civr-white] connected
[civr-blue] connected
```

Once connected, the status badges in the Fleet table turn green and live positions appear on the map.

> If a robot connects but shows no position for >10 s, the lighthouse sensor may still be initialising — wait a little longer.

---

### 5 — Select and run an algorithm

#### Pentagon (auto-centred formation)

1. Select **pentagon** in the Algorithm dropdown
2. Click **Run**
3. Robots drive to their assigned pentagon vertices (0.5 m radius around their centroid)
4. Coloured trails appear as robots move; target crosses (×) show each robot's vertex

#### Shapes (fixed world-space formation)

1. Select **shapes** in the dropdown — extra controls appear
2. Choose shape type, set center X/Y (metres, world frame), and radius
3. Click **Run**
4. Robots drive to the chosen formation at the specified world coordinates

#### Idle (stop all movement)

1. Select **idle** and click **Run** — robots stop at their current positions

---

### 6 — Stop robots

Click **Stop All** — runs `pkill -f agent.py` on each Pi. Motors stop immediately.

> You do **not** need to re-deploy between runs if `fleet.yaml` and `robot/` have not changed.
> Just **Start** again (lighthouse will be re-flashed, takes ~15 s).

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Deploy: connection refused / timeout | Pi not reachable | `ping civr-white.local` — check WiFi |
| Deploy: authentication failed | Wrong SSH password | Check `SSH_PASSWORD` in `.env` |
| Start: ok but robot never connects | Wrong `broker_host` in `fleet.yaml` | Set to laptop's current WiFi IP |
| Robot connects then drops after 5 s | Broker unreachable from Pi | Same as above |
| Robot connected, no position on map | Lighthouse still initialising | Wait ~10 s; check lighthouse UART wiring |
| UI stuck on "disconnected" | Server not running or wrong port | Confirm server is on port 8765 |
| Position jumps erratically | Lighthouse interference / occlusion | Clear line-of-sight to base stations |
