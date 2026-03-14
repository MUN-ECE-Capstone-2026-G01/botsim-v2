#!/usr/bin/env python3
# Lighthouse localization — LighthouseSensor threaded class.
# Based on Lighthouse-Deck/tools/decodeV2pos.py (new split version).
#
# Usage:
#   sensor = LighthouseSensor("/dev/ttyAMA2")
#   threading.Thread(target=sensor.run_continuous_reading, daemon=True).start()
#   # ... in control loop:
#   if sensor.check_new_data():
#       x, y, yaw = sensor.get_latest_reading()

import math
import struct
import threading
import serial
import cv2
import numpy as np

# Photodiode geometry
# https://www.bitcraze.io/documentation/hardware/lighthouse_deck/lighthouse_deck-datasheet.pdf
photodiode_positions = np.array([
    [ 0.0075,  0.015, 0],
    [-0.0075,  0.015, 0],
    [ 0.0075, -0.015, 0],
    [-0.0075, -0.015, 0],
], dtype=np.float32)

camera_matrix = np.eye(3)
distortion_coeffs = np.zeros(5)

# Lighthouse base-station cycle periods (48 MHz clock, halved for our 24 MHz)
PERIODS = [959000/2, 957000/2, 953000/2, 949000/2,
           947000/2, 943000/2, 941000/2, 939000/2,
           937000/2, 929000/2, 919000/2, 911000/2,
           907000/2, 901000/2, 893000/2, 887000/2]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def calculateAE(firstBeam, secondBeam):
    azimuth = ((firstBeam + secondBeam) / 2) - math.pi
    p = math.radians(60)
    beta = (secondBeam - firstBeam) - math.radians(120)
    elevation = math.atan(math.sin(beta / 2) / math.tan(p / 2))
    return (azimuth, elevation)


def ts_sub(a, b):
    return (a - b) & 0x00ffffff


def ts_add(a, b):
    return (a + b) & 0x00ffffff


def get_yaw_from_rvec(rvec):
    R, _ = cv2.Rodrigues(rvec)
    return math.atan2(R[2, 0], R[0, 0])


# ---------------------------------------------------------------------------
# Low-level decoding classes
# ---------------------------------------------------------------------------

class SweepData:
    def __init__(self, ts, width, offset, channel, slow_bit):
        self.ts = ts
        self.width = width
        self.offset = offset
        self.channel = channel
        self.slow_bit = slow_bit


class SweepBlock:
    def __init__(self):
        self.sensors = [None] * 4
        self.channel = self.ts = self.offset_sensor = self.slow_bit = None
        self.is_valid = False

    def push(self, sensor, ts, width, offset, channel, slow_bit):
        if self.sensors[sensor] is not None:
            return False
        self.sensors[sensor] = SweepData(ts, width, offset, channel, slow_bit)
        return True

    def process(self):
        if not all(self.sensors):
            return False

        channel_count = sum(1 for s in self.sensors if s.channel is not None)
        for s in self.sensors:
            if s.channel is not None:
                if self.channel is None:
                    self.channel, self.slow_bit = s.channel, s.slow_bit
                elif s.channel != self.channel:
                    return False

        if channel_count != 3:
            return False

        for s in self.sensors:
            s.channel, s.slow_bit = self.channel, self.slow_bit

        self.offset_sensor = next((s for s in self.sensors if s.offset), None)
        if not self.offset_sensor:
            return False

        for s in self.sensors:
            if not s.offset:
                s.offset = ts_add(self.offset_sensor.offset, ts_sub(s.ts, self.offset_sensor.ts))

        self.ts = min(s.ts for s in self.sensors)
        self.is_valid = True
        return True


class Angles:
    def __init__(self, channel):
        self.data = [None] * 4
        self.channel = channel

    def set(self, sensor, azimuth, elevation):
        self.data[sensor] = (azimuth, elevation)


class BaseStation:
    def __init__(self, channel):
        self.channel = channel
        self.prev_block = None

    def push(self, block):
        if block.channel != self.channel:
            return None
        if self.prev_block and self.is_second_sweep(self.prev_block, block):
            res = self.process(self.prev_block, block)
            self.prev_block = None
            return res
        self.prev_block = block
        return None

    def is_second_sweep(self, a, b):
        if a.sensors[0].offset > b.sensors[0].offset:
            return False
        return ts_sub(b.ts, a.ts) <= 220000

    def process(self, a, b):
        result = Angles(self.channel)
        for i in range(4):
            firstBeam  = (a.sensors[i].offset / PERIODS[self.channel]) * 2 * math.pi
            secondBeam = (b.sensors[i].offset / PERIODS[self.channel]) * 2 * math.pi
            result.set(i, *calculateAE(firstBeam, secondBeam))
        return result


class PulseProcessor:
    def __init__(self):
        self.block = None
        self.latest_pulse = 0

    def push(self, sensor, ts, width, offset, channel, slow_bit):
        if ts_sub(ts, self.latest_pulse) > 10000 and self.block:
            res = self.block if self.block.process() else None
            self.block = None
        else:
            res = None

        self.latest_pulse = ts
        if not self.block:
            self.block = SweepBlock()
        if not self.block.push(sensor, ts, width, offset, channel, slow_bit):
            self.block = None
        return res


# ---------------------------------------------------------------------------
# Threaded sensor class
# ---------------------------------------------------------------------------

class LighthouseSensor:
    """
    Reads raw lighthouse frames continuously in a background thread.
    The control loop polls check_new_data() / get_latest_reading() at its own rate.

    Coordinate mapping: PnP tvec[0] → x, tvec[2] → y  (camera Z = robot forward)
    """

    def __init__(self, source_path):
        self.source_path = source_path
        self.latest_x   = 0.0
        self.latest_y   = 0.0
        self.latest_yaw = 0.0
        self.has_new_data = False
        self.lock = threading.Lock()
        self.running = True

    def run_continuous_reading(self):
        if self.source_path.startswith("/dev/"):
            src = serial.Serial(self.source_path, 2 * 115200)
        else:
            src = open(self.source_path, "rb")

        pulse_processor = PulseProcessor()
        base_stations   = [BaseStation(i) for i in range(16)]

        # Wait for sync pattern: 12 consecutive 0xff bytes
        sync_pattern = [b'\xff'] * 12
        sync_buffer  = [b'\x00'] * 12
        while sync_pattern != sync_buffer and self.running:
            b = src.read(1)
            if not b:
                break
            sync_buffer = sync_buffer[1:] + [b]

        reading = src.read(12)
        while len(reading) == 12 and self.running:
            timestamp  = struct.unpack("<I", reading[9:]  + b'\x00')[0]
            offset_6   = struct.unpack("<I", reading[3:6] + b'\x00')[0]
            first_word = struct.unpack("<I", reading[:3]  + b'\x00')[0]

            offset = offset_6 * 4
            sensor = first_word & 0x03
            width  = (first_word >> 8) & 0xffff

            if ((first_word >> 7) & 0x01) == 0:
                identity = (first_word >> 2) & 0x1f
                channel  = identity >> 1
                slow_bit = identity & 1
            else:
                channel = slow_bit = None

            if offset_6 != 0xffffff:
                block = pulse_processor.push(sensor, timestamp, width, offset, channel, slow_bit)
                if block:
                    angles = base_stations[block.channel].push(block)
                    if angles:
                        self._update_pose(angles)

            reading = src.read(12)

    def _update_pose(self, angles_obj):
        plane_points = np.array(
            [[np.tan(a), np.tan(e)] for a, e in angles_obj.data],
            dtype=np.float32,
        )
        success, rvec, tvec = cv2.solvePnP(
            photodiode_positions, plane_points,
            camera_matrix, distortion_coeffs,
            flags=cv2.SOLVEPNP_IPPE,
        )
        if success:
            pos = tvec.flatten()
            yaw = get_yaw_from_rvec(rvec)
            with self.lock:
                self.latest_x     = pos[0]
                self.latest_y     = pos[2]  # PnP Z-axis = robot 2D Y
                self.latest_yaw   = yaw
                self.has_new_data = True

    def check_new_data(self):
        with self.lock:
            return self.has_new_data

    def get_latest_reading(self):
        """Returns (x, y, yaw) and clears the new-data flag."""
        with self.lock:
            self.has_new_data = False
            return self.latest_x, self.latest_y, self.latest_yaw
