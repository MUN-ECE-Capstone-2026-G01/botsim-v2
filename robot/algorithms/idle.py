#!/usr/bin/env python3
# Idle algorithm — stop motors and hold position.

from .base import SwarmAlgorithm


class Idle(SwarmAlgorithm):
    def compute_target(self, my_id: str, all_positions: dict):
        return None
