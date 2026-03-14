# Phase 1 Test Plan

Manual tests for step 1.6. Run in order — each test builds on the previous.

---

## Prerequisites

- One Pi (civr-1) powered on, lighthouse deck attached, lighthouse base station(s) active
- Host laptop on the same WiFi as the Pi
- `SSH_PASSWORD` available (or key-based auth set up)

---

## Step 0 — Deploy

```bash
# From the botsim-v2 repo root on your laptop:
rsync -av robot/ visor@civr-1.local:~/botsim/robot/
scp deck.sh visor@civr-1.local:~/deck.sh
```

Verify files landed:
```bash
ssh visor@civr-1.local "ls ~/botsim/robot/"
# Expected: agent.py  ekf.py  localization.py  motor_control.py
```

---

## Test 1 — Import sanity (no hardware needed yet)

SSH into the Pi and run:
```bash
ssh visor@civr-1.local
cd ~/botsim
source ~/Desktop/lighthousedeck/venv/bin/activate
python3 -c "from robot.localization import LighthouseSensor; print('localization OK')"
python3 -c "from robot.ekf import ExtendedKalmanFilter; print('ekf OK')"
python3 -c "
import sys; sys.path.insert(0, 'robot')
from localization import LighthouseSensor
from ekf import ExtendedKalmanFilter
print('imports OK')
"
```

**Pass criteria:** No import errors. (motor_control.py will fail to import because it opens /dev/ttyS0 at module level — that is expected and tested separately in Test 3.)

---

## Test 2 — EKF unit check (no hardware)

Run on the Pi (or laptop):
```bash
python3 - <<'EOF'
import sys; sys.path.insert(0, 'robot')
from ekf import ExtendedKalmanFilter
ekf = ExtendedKalmanFilter()
# Predict: drive straight at 0.3 m/s for 0.05 s
ekf.predict(0.3, 0.0, 0.05)
x, y, yaw = ekf.get_state()
assert abs(x - 0.015) < 1e-6, f"x wrong: {x}"
assert abs(y) < 1e-9,         f"y wrong: {y}"
print(f"predict OK: x={x:.4f}, y={y:.4f}, yaw={yaw:.4f}")
# Update back to origin
ekf.update(0.0, 0.0, 0.0)
x, y, yaw = ekf.get_state()
print(f"update OK:  x={x:.4f}, y={y:.4f}, yaw={yaw:.4f}")
# x should be pulled back toward 0 (Kalman gain < 1)
assert x < 0.015, "update did not correct state"
print("EKF tests passed")
EOF
```

**Pass criteria:** No assertion errors, printed values make sense.

---

## Test 3 — Serial port reachable

On the Pi:
```bash
python3 -c "import serial; s = serial.Serial('/dev/ttyS0', 115200, timeout=0.01); print('ttyS0 OK'); s.close()"
```

**Pass criteria:** Opens without error. If it fails, check ESP32 is connected and UART is enabled in raspi-config.

---

## Test 4 — Sensor read (lighthouse data, no motors)

Flash the lighthouse FPGA first, then test the sensor class in isolation:
```bash
# Flash (same as deck.sh does)
source ~/Desktop/lighthousedeck/venv/bin/activate
cd ~/Desktop/lighthousedeck/lighthouse-fpga
python3 tools/reboot.py /dev/ttyAMA2 && sleep 1
python3 ~/Desktop/lighthousedeck/lighthouse-bootloader/scripts/uart_bootloader.py /dev/ttyAMA2 lighthouse.bin

# Now run sensor in isolation for 10 seconds
python3 - <<'EOF'
import sys, time, threading
sys.path.insert(0, '/home/visor/botsim/robot')
from localization import LighthouseSensor

sensor = LighthouseSensor("/dev/ttyAMA2")
t = threading.Thread(target=sensor.run_continuous_reading, daemon=True)
t.start()
print("Waiting for data (10s)...")
deadline = time.time() + 10
readings = 0
while time.time() < deadline:
    if sensor.check_new_data():
        x, y, yaw = sensor.get_latest_reading()
        readings += 1
        print(f"  [{readings}] x={x:.3f}  y={y:.3f}  yaw={yaw:.2f}rad")
sensor.running = False
print(f"\nTotal readings in 10s: {readings}")
EOF
```

**Pass criteria:**
- At least several readings arrive within 10 seconds
- x, y, yaw values are plausible (not all zeros, not NaN)
- y value should roughly match physical distance from base station

---

## Test 5 — EKF + sensor integration (no motors)

Runs the EKF predict/update loop without sending motor commands:
```bash
python3 - <<'EOF'
import sys, time, threading
sys.path.insert(0, '/home/visor/botsim/robot')
from localization import LighthouseSensor
from ekf import ExtendedKalmanFilter

sensor = LighthouseSensor("/dev/ttyAMA2")
threading.Thread(target=sensor.run_continuous_reading, daemon=True).start()
time.sleep(2)

ekf = ExtendedKalmanFilter()
DT = 0.05

print("Running EKF loop for 10s (no motors)...")
deadline = time.time() + 10
while time.time() < deadline:
    loop_start = time.time()
    ekf.predict(0.0, 0.0, DT)
    if sensor.check_new_data():
        mx, my, myaw = sensor.get_latest_reading()
        ekf.update(mx, my, myaw)
    x, y, yaw = ekf.get_state()
    print(f"EKF  x={x:.3f}  y={y:.3f}  yaw={yaw:.2f}")
    time.sleep(max(0.0, DT - (time.time() - loop_start)))

sensor.running = False
EOF
```

**Pass criteria:**
- EKF output tracks lighthouse readings
- EKF state does not drift wildly between updates
- No crashes

---

## Test 6 — Full smoke test (robot drives)

Place the robot on the floor with clear line of sight to the base station.
The robot will drive toward `(0.0, 1.7)` then `(0.0, 0.8)` and cycle.

```bash
~/deck.sh
```

Or manually:
```bash
source ~/Desktop/lighthousedeck/venv/bin/activate
cd ~/Desktop/lighthousedeck/lighthouse-fpga
python3 tools/reboot.py /dev/ttyAMA2 && sleep 1
python3 ~/Desktop/lighthousedeck/lighthouse-bootloader/scripts/uart_bootloader.py /dev/ttyAMA2 lighthouse.bin
python3 ~/botsim/robot/agent.py /dev/ttyAMA2
```

**Pass criteria:**
- Robot localizes (Lighthouse readings printed within a few seconds)
- Robot moves toward the first waypoint `(0.0, 1.7)`
- Robot slows and stops when it reaches the waypoint (~0.1 m)
- Robot then proceeds toward the second waypoint `(0.0, 0.8)`
- `Ctrl+C` stops the robot cleanly (motors stop, no error)

**Things to observe:**
- `Lighthouse x=... y=... yaw=...` lines appear continuously
- `Target (0.0, 1.7) reached!` prints when waypoint is hit
- No serial errors or crashes during a 1-minute run

---

## Known limitations / things that are NOT tested in Phase 1

- Broker connection (Phase 2)
- Algorithm selection (Phase 2)
- Multi-robot behaviour (Phase 2+)
- Broker timeout / idle fallback (Phase 2)

---

## Notes on future deck.sh removal

shape-deployer eliminated deck.sh and inlines the reboot → flash → start sequence
via SSH from the host. In Phase 3, `fleet_manager.py` can do the same:

```python
# Instead of calling deck.sh, fleet_manager.start() can run:
cmd = (
    f"source {venv}/bin/activate && "
    f"cd {fpga_dir} && "
    f"python3 tools/reboot.py {uart} && sleep 1 && "
    f"python3 {bootloader} {uart} {lighthouse_bin} && "
    f"python3 ~/botsim/robot/agent.py {uart}"
)
ssh.exec_command(f"nohup bash -c '{cmd}' > /tmp/agent.log 2>&1 &")
```

This removes the need to deploy deck.sh separately.
