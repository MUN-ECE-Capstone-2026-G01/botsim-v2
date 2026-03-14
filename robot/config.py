#!/usr/bin/env python3
# Reads fleet.yaml and exposes per-robot and broker configuration.
# Called once at agent startup; sets motor_control.INVERT_V from fleet.yaml.
#
# Robot identity is derived from the Pi's hostname (e.g. "civr-1"),
# which must match an `id` entry in fleet.yaml.

import os
import socket
import yaml

# fleet.yaml lives one level up from robot/ (i.e. ~/botsim/fleet.yaml)
_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'fleet.yaml')


def _load():
    with open(_CONFIG_FILE) as f:
        fleet = yaml.safe_load(f)

    robot_id = socket.gethostname()
    robot_cfg = next((r for r in fleet['robots'] if r['id'] == robot_id), None)
    if robot_cfg is None:
        raise RuntimeError(
            f"Hostname '{robot_id}' not found in fleet.yaml. "
            f"Available IDs: {[r['id'] for r in fleet['robots']]}"
        )
    return robot_id, robot_cfg, fleet


_robot_id, _robot_cfg, _fleet = _load()

ROBOT_ID       = _robot_id
BROKER_HOST    = _fleet['broker_host']
BROKER_PORT    = int(_fleet['broker_port'])
BROKER_TIMEOUT = float(_fleet['broker_timeout'])
INVERT_V       = bool(_robot_cfg.get('invert_v', False))
