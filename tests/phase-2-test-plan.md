# Test Plans

---

## Phase 1 — Smoke test (step 1.6) ✅

### Deploy

```bash
rsync -av robot/ visor@civr-1.local:~/botsim/robot/
scp fleet.yaml visor@civr-1.local:~/botsim/fleet.yaml
scp deck.sh visor@civr-1.local:~/deck.sh
```

### Run

```bash
~/deck.sh
# or manually:
source ~/Desktop/lighthousedeck/venv/bin/activate
cd ~/Desktop/lighthousedeck/lighthouse-fpga
python3 tools/reboot.py /dev/ttyAMA2 && sleep 1
python3 ~/Desktop/lighthousedeck/lighthouse-bootloader/scripts/uart_bootloader.py /dev/ttyAMA2 lighthouse.bin
python3 ~/botsim/robot/agent.py /dev/ttyAMA2
```

**Pass criteria:** Robot localizes and drives to TARGET_LIST waypoints. Ctrl+C stops cleanly.

---

## Phase 2 — Broker + algorithms (step 2.9)

### Prerequisites

- Phase 3 broker must be running on the host laptop (`uvicorn host.main:app --port 8765`)
  - OR use the minimal test broker script below
- `broker_host` in `fleet.yaml` set to the host laptop's IP
- `fleet.yaml` deployed to Pi (`~/botsim/fleet.yaml`)

### Test 2.9a — No-broker graceful degradation

Run agent without any broker running. Robot should stay idle (not crash, not drive):

```bash
# On Pi — broker NOT running on host
python3 ~/botsim/robot/agent.py /dev/ttyAMA2
```

**Pass criteria:**

- `[broker] Connection error: ... — retrying in 2.0s` printed every 2s
- Robot stays stopped (no motor commands with non-zero v)
- Agent does not crash after 30+ seconds

### Test 2.9b — Broker connection and position publishing

Use a minimal echo broker on the laptop to verify the Pi connects and sends positions:

```python
# minimal_broker.py — run on host laptop
import asyncio, json, websockets

async def handler(ws):
    print(f"[broker] Client connected")
    async for msg in ws:
        data = json.loads(msg)
        print(f"[broker] Received: {data}")
        # Echo a state message back
        if data.get("type") == "hello":
            await ws.send(json.dumps({"type": "state", "positions": {}}))

async def main():
    async with websockets.serve(handler, "0.0.0.0", 8765):
        print("Minimal broker listening on :8765")
        await asyncio.Future()

asyncio.run(main())
```

```bash
# Laptop:
python3 minimal_broker.py
# Pi:
python3 ~/botsim/robot/agent.py /dev/ttyAMA2
```

**Pass criteria:**

- `[broker] Connected to ws://...` printed on Pi
- Position messages (`{"type": "position", ...}`) appear in the broker output at ~sensor rate
- `[sensor] x=... y=... yaw=...` lines printed on Pi

### Test 2.9c — Algorithm selection (idle → pentagon)

Extend the minimal broker to send an algorithm command after 5 seconds:

```python
# In minimal_broker.py handler, after receiving hello:
await asyncio.sleep(5)
await ws.send(json.dumps({"type": "algorithm", "name": "pentagon"}))
```

**Pass criteria:**

- After 5s: `[broker] Algorithm → pentagon` printed on Pi
- `[agent] Switching algorithm → pentagon` printed
- Robot begins driving toward its assigned vertex

### Test 2.9d — Broker timeout recovery

1. Start agent and broker, verify connection
2. Kill the broker process
3. Wait >5 seconds

**Pass criteria:**

- Robot stops within 5 seconds of broker going down
- `[broker] Connection error` messages appear
- After restarting broker, robot reconnects and resumes

### Test 2.9e — Pentagon with multiple robots

Deploy to 2+ Pis (same fleet.yaml, same broker). Start both.

**Pass criteria:**

- Both robots appear in broker state (positions dict has 2 entries)
- After `algorithm → pentagon`, robots drive to different vertices
- Each robot independently and deterministically selects the correct vertex

---

## Notes on fleet.yaml deployment

`fleet.yaml` must be on each Pi at `~/botsim/fleet.yaml`.
Add to deploy rsync command:

```bash
rsync -av robot/ visor@civr-1.local:~/botsim/robot/
scp fleet.yaml visor@civr-1.local:~/botsim/fleet.yaml
```

## Notes on future deck.sh removal (Phase 3)

shape-deployer eliminated deck.sh and inlines reboot/flash/start via SSH from the host.
In Phase 3, `fleet_manager.start()` can do the same:

```python
cmd = (
    f"source {venv}/bin/activate && "
    f"cd {fpga_dir} && "
    f"python3 tools/reboot.py {uart} && sleep 1 && "
    f"python3 {bootloader} {uart} {lighthouse_bin} && "
    f"python3 ~/botsim/robot/agent.py {uart}"
)
ssh.exec_command(f"nohup bash -c '{cmd}' > /tmp/agent.log 2>&1 &")
```
