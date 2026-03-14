#!/usr/bin/env python3
# Pentagon formation algorithm.
#
# Computes 5 vertices evenly spaced around the centroid of all known robot
# positions, then assigns robots to vertices using minimum total distance
# (Hungarian algorithm via scipy). Each robot independently runs the same
# deterministic assignment and picks its own vertex.

import math
import numpy as np
from scipy.optimize import linear_sum_assignment

from .base import SwarmAlgorithm

RADIUS = 0.5  # metres — distance from centroid to each vertex


class Pentagon(SwarmAlgorithm):
    def compute_target(self, my_id: str, all_positions: dict) -> tuple[float, float] | None:
        if not all_positions or my_id not in all_positions:
            return None

        # Centroid of all known robots
        xs = [p['x'] for p in all_positions.values()]
        ys = [p['y'] for p in all_positions.values()]
        cx = sum(xs) / len(xs)
        cy = sum(ys) / len(ys)

        # 5 vertices starting at top (π/2), going clockwise
        vertices = [
            (cx + RADIUS * math.cos(math.pi / 2 - i * 2 * math.pi / 5),
             cy + RADIUS * math.sin(math.pi / 2 - i * 2 * math.pi / 5))
            for i in range(5)
        ]

        # Sorted robot list for deterministic assignment across all robots
        robot_ids = sorted(all_positions.keys())
        n = min(len(robot_ids), 5)

        # Cost matrix: robot i → vertex j = Euclidean distance
        cost = np.zeros((n, 5))
        for i, rid in enumerate(robot_ids[:n]):
            rx = all_positions[rid]['x']
            ry = all_positions[rid]['y']
            for j, (vx, vy) in enumerate(vertices):
                cost[i, j] = math.sqrt((rx - vx) ** 2 + (ry - vy) ** 2)

        row_ind, col_ind = linear_sum_assignment(cost)
        assignment = {robot_ids[r]: vertices[c] for r, c in zip(row_ind, col_ind)}
        return assignment.get(my_id, None)
