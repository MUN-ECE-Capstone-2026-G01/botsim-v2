#!/usr/bin/env python3
# Main entry point for the robot agent.
# Replaces decodeV2pos.py as the script launched by deck.sh.
#
# Phase 1: behaviour is identical to decodeV2pos.py — localizes via lighthouse
# and drives to a fixed target. TARGET_X / TARGET_Y will be replaced by
# dynamic targets received from the host broker in Phase 2.

import sys
import os
import struct
import serial
import math

# Ensure robot/ directory is on the path so sibling modules are importable
# regardless of which directory the script is launched from.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from localization import (
    PulseProcessor, BaseStation, calculate_coordinates
)
from motor_control import drive_to_target, stop_motors, get_yaw_from_rvec

# --- Target position (hardcoded for Phase 1, will be dynamic in Phase 2) ---
TARGET_X = 0.0
TARGET_Y = 1.0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: {} <input.bin or /dev/tty...>".format(sys.argv[0]))
        sys.exit(1)

    if sys.argv[1].startswith("/dev/"):
        src = serial.Serial(sys.argv[1], 2 * 115200)
    else:
        src = open(sys.argv[1], "rb")

    pulse_processor = PulseProcessor()
    base_stations = [BaseStation(i) for i in range(16)]

    print("Waiting for sync ...")
    sync = [b'\xff'] * 12
    syncBuffer = [b'\x00'] * len(sync)
    while sync != syncBuffer:
        b = src.read(1)
        if len(b) < 1:
            sys.exit(1)
        syncBuffer.append(b)
        syncBuffer = syncBuffer[1:]

    print("Found sync!")

    reading = src.read(12)

    while len(reading) == 12:
        timestamp  = struct.unpack("<I", reading[9:]  + b'\x00')[0]
        beam_word  = struct.unpack("<I", reading[6:9] + b'\x00')[0]
        offset_6   = struct.unpack("<I", reading[3:6] + b'\x00')[0]
        first_word = struct.unpack("<I", reading[:3]  + b'\x00')[0]

        # Offset is expressed in a 6 MHz clock; timestamp uses a 24 MHz clock.
        offset = offset_6 * 4

        sensor = first_word & 0x03
        width  = (first_word >> 8) & 0xffff

        nPoly_ok = ((first_word >> 7) & 0x01) == 0
        if nPoly_ok:
            identity = (first_word >> 2) & 0x1f
            channel  = identity >> 1
            slow_bit = identity & 1
        else:
            channel  = None
            slow_bit = None

        # Sync frame — ignore it
        if offset_6 == 0xffffff:
            reading = src.read(12)
            continue

        block = pulse_processor.push(sensor, timestamp, width, offset, channel, slow_bit)
        if block:
            angles = base_stations[block.channel].push(block)
            if angles:
                angles.dump()
                result = calculate_coordinates(angles)
                if result is not None:
                    position, rotation_vec = result
                    yaw = math.degrees(get_yaw_from_rvec(rotation_vec))
                    print(f"Yaw: {yaw:.1f}deg")
                    drive_to_target(TARGET_X, TARGET_Y, position, rotation_vec)
                print()

        reading = src.read(12)
