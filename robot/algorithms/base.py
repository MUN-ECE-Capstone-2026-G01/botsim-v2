#!/usr/bin/env python3
# Abstract base class for all swarm algorithms.


class SwarmAlgorithm:
    def compute_target(self, my_id: str, all_positions: dict) -> tuple[float, float] | None:
        """
        Given the current global positions of all robots, return (target_x, target_y)
        for the robot identified by my_id, or None to stop motors.

        all_positions: dict mapping robot_id → {"x": float, "y": float, "theta": float}
        """
        raise NotImplementedError
