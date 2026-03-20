#!/usr/bin/env python3
# Shapes formation algorithm.
#
# Deploys robots to vertices of a configurable geometric shape at a fixed
# position in world space. Supports: point, line, triangle, square, pentagon,
# hexagon. Center and radius are specified as parameters when the algorithm is
# selected from the UI; they do not track the robot centroid.
#
# Assignment is optimal (Hungarian / scipy linear_sum_assignment), identical
# to pentagon.py. Each robot independently runs the same deterministic
# computation and returns its own assigned vertex.

import math
import numpy as np
from scipy.optimize import linear_sum_assignment

from .base import SwarmAlgorithm

# Number of vertices for each shape name
SHAPE_VERTEX_COUNT = {
    "point":    1,
    "line":     2,
    "triangle": 3,
    "square":   4,
    "pentagon": 5,
    "hexagon":  6,
}


def compute_vertices(shape: str, center_x: float, center_y: float, radius: float) -> list:
    """Return list of (x, y) vertex tuples for the requested shape."""
    n = SHAPE_VERTEX_COUNT.get(shape, 3)

    if n == 1:
        return [(center_x, center_y)]

    if n == 2:
        # Vertical line: top and bottom
        return [
            (center_x, center_y + radius),
            (center_x, center_y - radius),
        ]

    # Regular n-gon: start at top (π/2), go clockwise
    return [
        (
            center_x + radius * math.cos(math.pi / 2 - i * 2 * math.pi / n),
            center_y + radius * math.sin(math.pi / 2 - i * 2 * math.pi / n),
        )
        for i in range(n)
    ]


class Shapes(SwarmAlgorithm):
    def __init__(self, shape: str = "triangle", center_x: float = 0.0,
                 center_y: float = 0.0, radius: float = 0.5):
        self.shape    = shape
        self.center_x = center_x
        self.center_y = center_y
        self.radius   = radius
        self._vertices = compute_vertices(shape, center_x, center_y, radius)

    def compute_target(self, my_id: str, all_positions: dict) -> tuple[float, float] | None:
        if not all_positions or my_id not in all_positions:
            return None

        vertices  = self._vertices
        robot_ids = sorted(all_positions.keys())
        n         = min(len(robot_ids), len(vertices))

        # Cost matrix: n robots × len(vertices) vertices
        cost = np.zeros((n, len(vertices)))
        for i, rid in enumerate(robot_ids[:n]):
            rx = all_positions[rid]['x']
            ry = all_positions[rid]['y']
            for j, (vx, vy) in enumerate(vertices):
                cost[i, j] = math.hypot(rx - vx, ry - vy)

        row_ind, col_ind = linear_sum_assignment(cost)
        assignment = {robot_ids[r]: vertices[c] for r, c in zip(row_ind, col_ind)}
        return assignment.get(my_id, None)
