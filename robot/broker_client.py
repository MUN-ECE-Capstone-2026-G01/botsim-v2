#!/usr/bin/env python3
# WebSocket client — connects to the host broker in a background thread.
#
# Thread model:
#   - BrokerClient.start() launches a daemon thread running an asyncio event loop.
#   - The async loop maintains the WebSocket connection and auto-reconnects.
#   - The main (control) thread communicates via thread-safe accessors.

import asyncio
import json
import threading
import time

import websockets

RECONNECT_DELAY = 2.0  # seconds between reconnection attempts


class BrokerClient:
    def __init__(self, robot_id: str, broker_host: str, broker_port: int, timeout: float):
        self.robot_id = robot_id
        self.uri      = f"ws://{broker_host}:{broker_port}/ws/robot"
        self.timeout  = timeout

        self._lock               = threading.Lock()
        self._positions: dict    = {}
        self._pending_algorithm  = None   # str or None
        self._last_contact       = None   # float (time.time()) or None

        self._loop:   asyncio.AbstractEventLoop | None = None
        self._outbox: asyncio.Queue | None             = None

    # -----------------------------------------------------------------------
    # Public API — called from the main control thread
    # -----------------------------------------------------------------------

    def start(self):
        """Start the broker connection in a background daemon thread."""
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def publish_position(self, x: float, y: float, theta: float):
        """Queue a position update (non-blocking; dropped if not yet connected)."""
        if self._loop is None or self._outbox is None:
            return
        msg = json.dumps({
            "type":  "position",
            "id":    self.robot_id,
            "x":     round(x, 4),
            "y":     round(y, 4),
            "theta": round(theta, 4),
        })
        self._loop.call_soon_threadsafe(self._outbox.put_nowait, msg)

    def get_latest_state(self) -> dict:
        """Return the last-known positions of all robots."""
        with self._lock:
            return dict(self._positions)

    def get_new_algorithm(self) -> str | None:
        """Consume and return a pending algorithm name, or None."""
        with self._lock:
            name = self._pending_algorithm
            self._pending_algorithm = None
            return name

    def is_timed_out(self) -> bool:
        """True if broker has been unreachable for longer than timeout seconds."""
        with self._lock:
            if self._last_contact is None:
                return True
            return (time.time() - self._last_contact) > self.timeout

    # -----------------------------------------------------------------------
    # Internal async machinery (runs inside the background thread)
    # -----------------------------------------------------------------------

    def _run(self):
        self._loop   = asyncio.new_event_loop()
        self._outbox = asyncio.Queue()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._connect_loop())

    async def _connect_loop(self):
        while True:
            try:
                async with websockets.connect(self.uri) as ws:
                    print(f"[broker] Connected to {self.uri}")
                    await ws.send(json.dumps({"type": "hello", "id": self.robot_id}))
                    with self._lock:
                        self._last_contact = time.time()

                    send_task = asyncio.ensure_future(self._sender(ws))
                    try:
                        await self._receiver(ws)
                    finally:
                        send_task.cancel()
                        print("[broker] Disconnected")

            except Exception as e:
                print(f"[broker] {e} — retrying in {RECONNECT_DELAY}s")

            await asyncio.sleep(RECONNECT_DELAY)

    async def _sender(self, ws):
        """Forward messages from the outbox to the WebSocket."""
        while True:
            msg = await self._outbox.get()
            await ws.send(msg)

    async def _receiver(self, ws):
        """Process incoming messages from the broker."""
        async for raw in ws:
            msg = json.loads(raw)
            with self._lock:
                self._last_contact = time.time()
            if msg.get("type") == "state":
                with self._lock:
                    self._positions = msg["positions"]
            elif msg.get("type") == "algorithm":
                with self._lock:
                    self._pending_algorithm = msg["name"]
                print(f"[broker] Algorithm → {msg['name']}")
