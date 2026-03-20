#!/usr/bin/env python3
# WebSocket connection manager for the FastAPI broker.
#
# Maintains:
#   - Active Pi robot connections  (robot_id → WebSocket)
#   - Active UI browser connections (list of WebSockets)
#   - Latest position state per robot
#
# All public methods are async and safe to call from FastAPI route handlers.

import json
import time

from fastapi import WebSocket


class BrokerState:
    def __init__(self):
        self._robots: dict[str, WebSocket] = {}     # robot_id → ws
        self._ui_clients: list[WebSocket] = []
        self.positions: dict[str, dict] = {}         # robot_id → {x, y, theta, last_seen}

    # -----------------------------------------------------------------------
    # Connection registration (accept() is done in main.py before calling these)
    # -----------------------------------------------------------------------

    def register_robot(self, robot_id: str, ws: WebSocket):
        self._robots[robot_id] = ws

    def unregister_robot(self, robot_id: str):
        self._robots.pop(robot_id, None)

    def register_ui(self, ws: WebSocket):
        self._ui_clients.append(ws)

    def unregister_ui(self, ws: WebSocket):
        try:
            self._ui_clients.remove(ws)
        except ValueError:
            pass

    # -----------------------------------------------------------------------
    # Inbound message handling
    # -----------------------------------------------------------------------

    async def handle_robot_message(self, robot_id: str, data: dict):
        """Process a message received from a Pi agent."""
        if data.get("type") == "position":
            self.positions[robot_id] = {
                "x":         data["x"],
                "y":         data["y"],
                "theta":     data["theta"],
                "last_seen": time.time(),
            }
            await self._broadcast_state()

    # -----------------------------------------------------------------------
    # Outbound broadcasts
    # -----------------------------------------------------------------------

    async def broadcast_algorithm(self, name: str, params: dict = {}):
        """Send an algorithm-switch command to all connected Pi agents."""
        msg = json.dumps({"type": "algorithm", "name": name, "params": params})
        for ws in list(self._robots.values()):
            await _try_send(ws, msg)

    async def broadcast_log(self, message: str):
        """Send a log line to all connected UI clients."""
        msg = json.dumps({"type": "log", "message": message})
        for ws in list(self._ui_clients):
            await _try_send(ws, msg)

    async def broadcast_disconnect(self, robot_id: str):
        """Notify UI clients that a robot went offline."""
        await self._broadcast_state()

    async def _broadcast_state(self):
        """Fan out latest positions to all Pis and all UI clients.
        Pis receive all known positions (needed for algorithm computation).
        UI clients receive only currently-connected robots so offline status is accurate."""
        online_pos = {rid: pos for rid, pos in self.positions.items() if rid in self._robots}
        all_msg    = json.dumps({"type": "state", "positions": online_pos})
        ui_msg     = json.dumps({"type": "state", "positions": online_pos})

        for ws in list(self._robots.values()):
            await _try_send(ws, all_msg)
        for ws in list(self._ui_clients):
            await _try_send(ws, ui_msg)

    # -----------------------------------------------------------------------
    # Query
    # -----------------------------------------------------------------------

    def get_fleet_status(self, robots_config: list) -> list:
        """Return per-robot status suitable for GET /robots."""
        now = time.time()
        result = []
        for r in robots_config:
            rid = r["id"]
            pos = self.positions.get(rid)
            online = rid in self._robots
            result.append({
                "id":       rid,
                "host":     r["host"],
                "online":   online,
                "position": pos,
            })
        return result


async def _try_send(ws: WebSocket, msg: str):
    try:
        await ws.send_text(msg)
    except Exception:
        pass


# Module-level singleton used by main.py
broker = BrokerState()
