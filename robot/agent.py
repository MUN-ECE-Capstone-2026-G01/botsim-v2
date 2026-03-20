#!/usr/bin/env python3
# Robot agent — main entry point, launched by deck.sh.
#
# Reads fleet.yaml for robot identity and broker address.
# Connects to host broker via WebSocket; receives algorithm selections.
# Runs a 20 Hz EKF control loop; falls back to idle if broker unreachable.

import sys
import os
import time
import threading

# Ensure robot/ is importable regardless of launch directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import motor_control
from localization import LighthouseSensor
from ekf import ExtendedKalmanFilter
from broker_client import BrokerClient
from algorithms.idle import Idle

# Apply per-robot hardware config from fleet.yaml
motor_control.INVERT_V = config.INVERT_V


def load_algorithm(name: str, params: dict = {}):
    """Instantiate a swarm algorithm by name, forwarding any params."""
    if name == "idle":
        return Idle()
    if name == "pentagon":
        from algorithms.pentagon import Pentagon
        return Pentagon()
    if name == "shapes":
        from algorithms.shapes import Shapes
        return Shapes(
            shape    = params.get("shape",    "triangle"),
            center_x = float(params.get("center_x", 0.0)),
            center_y = float(params.get("center_y", 0.0)),
            radius   = float(params.get("radius",   0.5)),
        )
    print(f"[agent] Unknown algorithm '{name}', falling back to idle")
    return Idle()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <input.bin or /dev/ttyAMA2>")
        sys.exit(1)

    sensor_path = sys.argv[1]

    print(f"[agent] Robot ID : {config.ROBOT_ID}")
    print(f"[agent] Broker   : {config.BROKER_HOST}:{config.BROKER_PORT}")
    print(f"[agent] Timeout  : {config.BROKER_TIMEOUT}s")
    print(f"[agent] INVERT_V : {config.INVERT_V}")

    # --- Sensor (background thread) ---
    sensor = LighthouseSensor(sensor_path)
    threading.Thread(target=sensor.run_continuous_reading, daemon=True).start()
    print("[agent] Waiting for initial sensor sync...")
    time.sleep(2)

    # --- Broker (background thread) ---
    broker = BrokerClient(
        robot_id=config.ROBOT_ID,
        broker_host=config.BROKER_HOST,
        broker_port=config.BROKER_PORT,
        timeout=config.BROKER_TIMEOUT,
    )
    broker.start()

    # --- EKF + algorithm state ---
    ekf               = ExtendedKalmanFilter()
    current_algorithm = Idle()
    current_v         = 0.0
    current_w         = 0.0

    print(f"[agent] Starting control loop at {motor_control.LOOP_FREQ:.0f} Hz ...")
    try:
        while True:
            loop_start = time.time()

            # 1. Kinematic prediction
            ekf.predict(current_v, current_w, motor_control.DT)

            # 2. Lighthouse update + publish position to broker
            if sensor.check_new_data():
                x, y, yaw = sensor.get_latest_reading()
                ekf.update(x, y, yaw)
                broker.publish_position(x, y, yaw)
                print(f"[sensor] x={x:.3f}  y={y:.3f}  yaw={yaw:.2f}")

            est_x, est_y, est_yaw = ekf.get_state()

            # 3. Broker timeout → stop and wait for reconnection
            if broker.is_timed_out():
                motor_control.stop_motors()
                current_v, current_w = 0.0, 0.0
                time.sleep(max(0.0, motor_control.DT - (time.time() - loop_start)))
                continue

            # 4. Algorithm switch
            new_algo = broker.get_new_algorithm()
            if new_algo is not None:
                name, params = new_algo
                print(f"[agent] Switching algorithm → {name} params={params}")
                current_algorithm = load_algorithm(name, params)

            # 5. Compute target and drive
            all_positions = broker.get_latest_state()
            target = current_algorithm.compute_target(config.ROBOT_ID, all_positions)

            if target is None:
                motor_control.stop_motors()
                current_v, current_w = 0.0, 0.0
            else:
                target_x, target_y = target
                current_v, current_w = motor_control.go_to_target(
                    est_x, est_y, est_yaw, target_x, target_y
                )
                motor_control.send_command(current_v, current_w)

            # 6. Rate limiting
            elapsed = time.time() - loop_start
            time.sleep(max(0.0, motor_control.DT - elapsed))

    except KeyboardInterrupt:
        print("\n[agent] Stopping robot...")
        motor_control.stop_motors()
        sensor.running = False
