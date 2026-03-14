#!/usr/bin/env python3
# Extended Kalman Filter for robot pose estimation.
# Based on Lighthouse-Deck/tools/ekf.py
#
# Fuses:
#   - predict(v, w, dt) — differential-drive kinematic model
#   - update(x, y, yaw) — direct Lighthouse pose measurement
#
# State vector: [x, y, yaw]

import math
import numpy as np


class ExtendedKalmanFilter:
    def __init__(self, initial_x=0.0, initial_y=0.0, initial_yaw=0.0):
        self.state = np.array([initial_x, initial_y, initial_yaw], dtype=float)

        # Covariance matrix — initial uncertainty
        self.P = np.eye(3) * 0.1

        # Q: process noise (wheel odometry / kinematics uncertainty)
        self.Q = np.diag([0.05, 0.05, 0.02])

        # R: measurement noise — Lighthouse is very accurate, keep small
        self.R = np.diag([0.01, 0.01, 0.005])

    def predict(self, v, w, dt):
        """Kinematic prediction step based on last motor commands."""
        x, y, theta = self.state

        if abs(w) < 1e-5:
            # Straight-line motion
            self.state[0] += v * math.cos(theta) * dt
            self.state[1] += v * math.sin(theta) * dt
        else:
            # Arc motion
            self.state[0] += (v / w) * (math.sin(theta + w * dt) - math.sin(theta))
            self.state[1] += (v / w) * (math.cos(theta) - math.cos(theta + w * dt))
        self.state[2] += w * dt

        # Normalize yaw to [-pi, pi]
        self.state[2] = (self.state[2] + math.pi) % (2 * math.pi) - math.pi

        # Jacobian of the state transition function
        F = np.eye(3)
        F[0, 2] = -v * math.sin(theta) * dt
        F[1, 2] =  v * math.cos(theta) * dt

        self.P = F @ self.P @ F.T + self.Q

    def update(self, meas_x, meas_y, meas_yaw):
        """Measurement correction from Lighthouse sensor."""
        Z = np.array([meas_x, meas_y, meas_yaw])

        # H is identity — we measure state variables directly
        H = np.eye(3)

        Y = Z - (H @ self.state)
        # Normalize angular residual
        Y[2] = (Y[2] + math.pi) % (2 * math.pi) - math.pi

        S = H @ self.P @ H.T + self.R
        K = self.P @ H.T @ np.linalg.inv(S)

        self.state = self.state + (K @ Y)
        self.P = (np.eye(3) - K @ H) @ self.P

    def get_state(self):
        """Returns (x, y, yaw)."""
        return self.state[0], self.state[1], self.state[2]
