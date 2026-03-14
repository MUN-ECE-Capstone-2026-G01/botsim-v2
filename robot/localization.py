#!/usr/bin/env python3
# Lighthouse localization logic extracted from decodeV2pos.py.
# calculate_coordinates() returns (position, rotation_vec) instead of
# calling drive_to_target directly — the caller (agent.py) decides what to do.

import math
import cv2
import numpy as np

# From https://www.bitcraze.io/documentation/hardware/lighthouse_deck/lighthouse_deck-datasheet.pdf
photodiode_positions = np.array([
    [ 0.0075, 0.015  , 0], # 0
    [-0.0075, 0.015,  0], # 1
    [0.0075, -0.015, 0], # 2
    [ -0.0075, -0.015,  0]  # 3
], dtype=np.float32)

camera_matrix = np.eye(3)
distortion_coeffs = np.zeros(5)  # No distortion as we are using laser beams.


def calculateAE(firstBeam, secondBeam):
    azimuth = ((firstBeam + secondBeam) / 2) - math.pi
    p = math.radians(60)
    beta = (secondBeam - firstBeam) - math.radians(120)
    elevation = math.atan(math.sin(beta/2)/math.tan(p/2))
    return (azimuth, elevation)


def ts_sub(a, b):
    return (a - b) & 0x00ffffff


def ts_add(a, b):
    return (a + b) & 0x00ffffff


# The cycle times from the Lighthouse base stations is expressed in a 48 MHz clock,
# we use 24 MHz, hence the / 2.
PERIODS = [959000 / 2, 957000 / 2,
           953000 / 2, 949000 / 2,
           947000 / 2, 943000 / 2,
           941000 / 2, 939000 / 2,
           937000 / 2, 929000 / 2,
           919000 / 2, 911000 / 2,
           907000 / 2, 901000 / 2,
           893000 / 2, 887000 / 2]


class SweepData:
    def __init__(self, ts, width, offset, channel, slow_bit):
        self.ts = ts
        self.width = width
        self.offset = offset
        self.channel = channel
        self.slow_bit = slow_bit

    def dump(self, sensor_nr, mark=False):
        if self.channel == None:
            chan_s = ' -'
        else:
            chan_s = "{:2}".format(self.channel + 1)

        if self.slow_bit == None:
            slow_s = '-'
        else:
            slow_s = int(self.slow_bit)

        mark_s = ''
        if mark:
            mark_s = '<--'

        print("Sensor:{}  TS:{:06x}  Width:{:4}  Chan:{}({})  offset:{:-6d}  {}".format(
            sensor_nr, self.ts, self.width, chan_s, slow_s, self.offset, mark_s))


class SweepBlock:
    def __init__(self):
        self.sensors = [None, None, None, None]
        self.channel = None
        self.ts = None
        self.is_valid = False
        self.offset_sensor = None
        self.slow_bit = None

    def print_err(self, s):
        # Enable this print to see why a frame is discarded
        # print(s)
        # self.dump()
        pass

    def push(self, sensor, ts, width, offset, channel, slow_bit):
        if self.sensors[sensor] != None:
            return False
        self.sensors[sensor] = SweepData(ts, width, offset, channel, slow_bit)
        return True

    def process(self):
        # Check we have data for all sensors
        for sensor in self.sensors:
            if not sensor:
                self.print_err("Sensor missing - discard sweep")
                return False

        # Channel. Should all be the same except one that is None
        channel_count = 0
        for sensor in self.sensors:
            if sensor.channel != None:
                channel_count += 1

                if self.channel == None:
                    self.channel = sensor.channel
                    self.slow_bit = sensor.slow_bit

                if sensor.channel != self.channel:
                    self.print_err("Duplicate channels - discard sweep")
                    return False

        if channel_count != 3:
            self.print_err("Channel missing - discard sweep")
            return False

        # Set channel in all sensors
        for sensor in self.sensors:
            sensor.channel = self.channel
            sensor.slow_bit = self.slow_bit

        # offset. Should be offset on one and only one sensor
        self.offset_sensor = None
        for sensor in self.sensors:
            if sensor.offset:
                if self.offset_sensor:
                    self.print_err("Duplicate offset - discard sweep")
                    return False
                self.offset_sensor = sensor

        if not self.offset_sensor:
            self.print_err("No offset found - discard sweep")
            return False

        # Calculate other offsets
        for sensor in self.sensors:
            if not sensor.offset:
                ts_delta = ts_sub(sensor.ts, self.offset_sensor.ts)
                sensor.offset = ts_add(self.offset_sensor.offset, ts_delta)

        # Find first time stamp
        for sensor in self.sensors:
            if not self.ts:
                self.ts = sensor.ts

            if sensor.ts < self.ts:
                self.ts = sensor.ts

        self.is_valid = True
        return True

    def dump(self):
        sensor_nr = 0
        for sensor in self.sensors:
            if sensor:
                mark = (sensor == self.offset_sensor)
                sensor.dump(sensor_nr, mark)
            else:
                print("Missing")

            sensor_nr += 1


class Angles:
    def __init__(self, channel):
        self.data = [None, None, None, None]
        self.channel = channel

    def set(self, sensor, azimuth, elevation):
        self.data[sensor] = (azimuth, elevation)

    def dump(self):
        sensor_nr = 0
        for d in self.data:
            print("Chan:{:2d} Sensor:{} azimuth:{:8.2f} elevation:{:8.2f}".format(
                self.channel + 1, sensor_nr, math.degrees(d[0]), math.degrees(d[1])))
            sensor_nr += 1


class BaseStation:
    def __init__(self, channel):
        self.channel = channel
        self.prev_block = None

    def push(self, block):
        result = None

        if block.channel != self.channel:
            print("Wrong channel!")
            return result

        if self.prev_block:
            if self.is_second_sweep(self.prev_block, block):
                result = self.process(self.prev_block, block)
                self.prev_block = None
            else:
                self.prev_block = block
        else:
            self.prev_block = block

        return result

    def is_second_sweep(self, a, b):
        if a.sensors[0].offset > b.sensors[0].offset:
            return False

        dt = ts_sub(b.ts, a.ts)
        # 220000 ticks is around 180 degrees
        if dt > 220000:
            return False

        return True

    def process(self, a, b):
        result = Angles(self.channel)

        for i in range(4):
            offset0 = a.sensors[i].offset
            offset1 = b.sensors[i].offset
            period = PERIODS[self.channel]

            firstBeam = (offset0 / period) * 2 * math.pi
            secondBeam = (offset1 / period) * 2 * math.pi
            azimuth, elevation = calculateAE(firstBeam, secondBeam)

            result.set(i, azimuth, elevation)

        return result


class PulseProcessor:
    def __init__(self):
        self.block = None
        self.latest_pulse = 0

    def push(self, sensor, ts, width, offset, channel, slow_bit):
        result = None

        delta = ts_sub(ts, self.latest_pulse)
        if delta > 10000:
            if self.block:
                if self.block.process():
                    result = self.block
                self.block = None
        self.latest_pulse = ts

        if not self.block:
            self.block = SweepBlock()

        if not self.block.push(sensor, ts, width, offset, channel, slow_bit):
            print("Drop block")
            self.block = None

        return result


def calculate_coordinates(angles_obj):
    """
    Compute robot position and orientation from lighthouse angle data.
    Returns (position, rotation_vec) where position is a 3-element array
    [X, Y, Z], or None if solvePnP fails.
    """
    plane_points = []
    i = 0
    while i < 4:
        azimuth, elevation = angles_obj.data[i]
        u = np.tan(azimuth)
        v = np.tan(elevation)
        plane_points.append([u, v])
        i += 1

    plane_points = np.array(plane_points, dtype=np.float32)
    success_bool, rotation_vec, translation_vec = cv2.solvePnP(
        photodiode_positions,
        plane_points,
        camera_matrix,
        distortion_coeffs,
        flags=cv2.SOLVEPNP_IPPE
    )
    print(rotation_vec)
    if success_bool:
        position = translation_vec.flatten()
        distance = np.linalg.norm(position)
        print(f"X={position[0]:.4f}, Y={position[1]:.4f}, Z={position[2]:.4f} "
              f"Dist: {distance:.4f}m")
        return position, rotation_vec

    return None
