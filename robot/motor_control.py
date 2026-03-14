#!/usr/bin/env python3
# Motor control logic extracted from decodeV2pos.py.
# drive_to_target() now accepts target_x, target_y as parameters
# instead of having them hardcoded.

import math
import time
import serial
import cv2
import numpy as np

# AMA2 is for UART (to ESP32)
SERIAL_PORT = '/dev/ttyAMA2'
BAUD_RATE = 115200

# Tunable gains
Kv = 0.35
Kh = 10

# Safety caps
MAX_V = 0.5   # m/s
MAX_W = 4     # rad/s
STOP_DIST = 0.1

ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.01)


def get_yaw_from_rvec(rvec):
    R, _ = cv2.Rodrigues(rvec)
    theta = math.atan2(R[2, 0], R[0, 0])
    return theta


def stop_motors():
    """Send a zero velocity command to halt the robot."""
    cmd = "0,0\n"
    ser.write(cmd.encode())


def drive_to_target(target_x, target_y, current_location, rotation_vec):
    print(f"Navigating to ({target_x}, {target_y})")

    current_x = current_location[0]
    current_y = current_location[2]
    current_theta = get_yaw_from_rvec(rotation_vec)

    dx = target_x - current_x
    dy = target_y - current_y
    distance = math.sqrt(dx**2 + dy**2)
    print(f"dy:{dy} dx:{dx} navigation distance:{distance}")

    # Check success
    if distance < STOP_DIST:
        print("Target Reached!")
        stop_motors()
        return

    base = dx

    angle_to_target = math.atan2(dy, base)
    print(f"Angle to the target: {math.degrees(angle_to_target)}deg")
    heading_error = current_theta
    print(f"heading_error(How much the robot needs to turn) {math.degrees(heading_error)}deg")
    while heading_error > math.pi: heading_error -= 2 * math.pi
    while heading_error < -math.pi: heading_error += 2 * math.pi

    if abs(heading_error) > math.radians(60):
        v = 0.0
        w = Kh * heading_error
    else:
        v = Kv * distance * math.cos(heading_error)
        w = Kh * heading_error

    v = max(min(v, MAX_V), -MAX_V)
    w = max(min(w, MAX_W), -MAX_W)
    cmd = f"{v:.2f},{-w:.2f}\n"
    print(cmd)
    ser.write(cmd.encode())

    time.sleep(0.01)
