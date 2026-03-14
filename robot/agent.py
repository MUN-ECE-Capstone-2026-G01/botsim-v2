#!/usr/bin/env python3
# Robot agent — main entry point, launched by deck.sh.
#
# Phase 1 behaviour: drives through TARGET_LIST waypoints using pure_pursuit,
# with EKF fusing lighthouse measurements and kinematic prediction.
#
# Architecture:
#   - LighthouseSensor runs in a background daemon thread (continuous read)
#   - Main loop runs at fixed LOOP_FREQ Hz (control is decoupled from sensor rate)
#   - EKF.predict() runs every loop tick; EKF.update() runs only when new data arrives
#
# Phase 2 will add broker_client + swarm algorithms; target will come from
# current_algorithm.compute_target() rather than the hardcoded TARGET_LIST.

import sys
import os
import time
import threading

# Ensure robot/ directory is importable regardless of launch directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from localization import LighthouseSensor
from ekf import ExtendedKalmanFilter
from motor_control import (
    pure_pursuit, stop_motors, send_command,
    LOOP_FREQ, DT,
)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <input.bin or /dev/ttyAMA2>")
        sys.exit(1)

    sensor_path = sys.argv[1]

    # Start lighthouse sensor in background
    sensor = LighthouseSensor(sensor_path)
    sensor_thread = threading.Thread(target=sensor.run_continuous_reading, daemon=True)
    sensor_thread.start()

    print("Waiting for initial sensor sync...")
    time.sleep(2)

    ekf = ExtendedKalmanFilter()
    current_v, current_w = 0.0, 0.0

    print(f"Starting control loop at {LOOP_FREQ:.0f} Hz ...")
    try:
        while True:
            loop_start = time.time()

            # --- Predict (runs every tick using last motor command) ---
            ekf.predict(current_v, current_w, DT)

            # --- Update (only when sensor has a fresh frame) ---
            if sensor.check_new_data():
                meas_x, meas_y, meas_yaw = sensor.get_latest_reading()
                print(f"Lighthouse  x={meas_x:.3f}  y={meas_y:.3f}  yaw={meas_yaw:.2f}rad")
                ekf.update(meas_x, meas_y, meas_yaw)

            # --- Control ---
            est_x, est_y, est_yaw = ekf.get_state()
            current_v, current_w  = pure_pursuit(est_x, est_y, est_yaw)
            send_command(current_v, current_w)

            # --- Rate limiting ---
            elapsed = time.time() - loop_start
            time.sleep(max(0.0, DT - elapsed))

    except KeyboardInterrupt:
        print("\nStopping robot...")
        stop_motors()
        sensor.running = False
