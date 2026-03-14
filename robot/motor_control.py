#!/usr/bin/env python3
# Motor control — go_to_position, pure_pursuit, stop_motors.
# Based on Lighthouse-Deck/tools/drive.py
#
# Serial port: /dev/ttyS0 (ESP32 motor driver, 115200 baud)
# NOTE: /dev/ttyAMA2 is the lighthouse UART — do not use it here.
#
# Phase 1: TARGET_LIST is a hardcoded waypoint sequence.
# Phase 2: agent.py will pass targets from the swarm algorithm instead.

import math
import serial

# ---------------------------------------------------------------------------
# Serial
# ---------------------------------------------------------------------------

MOTOR_PORT = '/dev/ttyS0'
BAUD_RATE  = 115200

ser = serial.Serial(MOTOR_PORT, BAUD_RATE, timeout=0.01)

# ---------------------------------------------------------------------------
# Control loop timing (used by agent.py)
# ---------------------------------------------------------------------------

LOOP_FREQ = 20.0
DT        = 1.0 / LOOP_FREQ

# ---------------------------------------------------------------------------
# Driving constants
# ---------------------------------------------------------------------------

Kv        = 0.2
Kh        = 5.0
MAX_V     = 0.5    # m/s
MAX_W     = 4.0    # rad/s
STOP_DIST = 0.1    # m — consider target reached within this radius

LOOKAHEAD_DIST = 0.4  # m — pure pursuit lookahead

# Whether to negate forward velocity before sending to the ESP32.
# Depends on motor wiring polarity — set per robot in fleet.yaml.
# Phase 2: config.py will set this from fleet.yaml at startup.
INVERT_V = True

# ---------------------------------------------------------------------------
# Phase 1 waypoints (replaced by algorithm target in Phase 2)
# ---------------------------------------------------------------------------

# TARGET_LIST = [(0.0, 1.7), (0.0, 0.8)]
TARGET_LIST = [(-0.5, 0.4), (0.5, 0.4)]
current_target_idx = 0


# ---------------------------------------------------------------------------
# Motor commands
# ---------------------------------------------------------------------------

def stop_motors():
    """Send a zero-velocity command."""
    ser.write(b"0.00,0.00\n")


def send_command(v, w):
    """Send a velocity command.
    v is negated if INVERT_V is set (motor wiring polarity).
    w is negated to match ESP32 angular convention.
    """
    if INVERT_V:
        v = -v
    cmd = f"{v:.2f},{-w:.2f}\n"
    ser.write(cmd.encode())


# ---------------------------------------------------------------------------
# Control laws
# ---------------------------------------------------------------------------

def go_to_position(current_x, current_y, current_theta):
    """
    Proportional heading + distance controller.
    Returns (v, w). Advances TARGET_LIST index when target is reached.
    """
    global current_target_idx

    target_x, target_y = TARGET_LIST[current_target_idx % len(TARGET_LIST)]

    dx = target_x - current_x
    dy = target_y - current_y
    distance = math.sqrt(dx**2 + dy**2)

    if distance < STOP_DIST:
        print(f"Target ({target_x}, {target_y}) reached!")
        current_target_idx = (current_target_idx + 1) % len(TARGET_LIST)
        return 0.0, 0.0

    angle_to_target = math.atan2(dx, -dy)
    heading_error   = angle_to_target - current_theta

    while heading_error >  math.pi: heading_error -= 2 * math.pi
    while heading_error < -math.pi: heading_error += 2 * math.pi

    if abs(heading_error) > math.radians(60):
        v = 0.0
        w = Kh * heading_error
    else:
        v = Kv * distance * math.cos(heading_error)
        w = Kh * heading_error

    v = max(min(v, MAX_V), -MAX_V)
    w = max(min(w, MAX_W), -MAX_W)
    return v, w


def pure_pursuit(current_x, current_y, current_theta):
    """
    Lookahead path follower along TARGET_LIST.
    Smoother than go_to_position for multi-waypoint navigation.
    Returns (v, w). Advances TARGET_LIST index when waypoint is reached.
    """
    global current_target_idx

    idx      = current_target_idx % len(TARGET_LIST)
    prev_idx = (current_target_idx - 1) % len(TARGET_LIST)

    target_x, target_y = TARGET_LIST[idx]
    start_x,  start_y  = TARGET_LIST[prev_idx]

    dx_actual = target_x - current_x
    dy_actual = target_y - current_y
    distance  = math.sqrt(dx_actual**2 + dy_actual**2)

    if distance < STOP_DIST:
        print(f"Target ({target_x}, {target_y}) reached!")
        current_target_idx = (current_target_idx + 1) % len(TARGET_LIST)
        return 0.0, 0.0

    # Project robot position onto path segment and compute lookahead point
    px = target_x - start_x
    py = target_y - start_y
    path_len = math.sqrt(px**2 + py**2)

    if path_len == 0:
        aim_x, aim_y = target_x, target_y
    else:
        rx   = current_x - start_x
        ry   = current_y - start_y
        proj = (rx * px + ry * py) / path_len
        aim_dist = max(0.0, min(proj + LOOKAHEAD_DIST, path_len))
        aim_x = start_x + (px / path_len) * aim_dist
        aim_y = start_y + (py / path_len) * aim_dist

    dx_aim = aim_x - current_x
    dy_aim = aim_y - current_y

    angle_to_target = math.atan2(dx_aim, -dy_aim)
    heading_error   = angle_to_target - current_theta

    while heading_error >  math.pi: heading_error -= 2 * math.pi
    while heading_error < -math.pi: heading_error += 2 * math.pi

    if abs(heading_error) > math.radians(60):
        v = 0.0
        w = Kh * heading_error
    else:
        v = Kv * distance * math.cos(heading_error)
        w = Kh * heading_error

    v = max(min(v, MAX_V), -MAX_V)
    w = max(min(w, MAX_W), -MAX_W)
    return v, w
