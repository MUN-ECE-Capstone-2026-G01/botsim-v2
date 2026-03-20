#!/usr/bin/env python3
# FastAPI application — broker + fleet manager + REST API.
#
# Start with:
#   uv run uvicorn host.main:app --host 0.0.0.0 --port 8765
#
# Port must match broker_port in fleet.yaml (robots connect to ws://host:8765/ws/robot)
#
# WebSocket endpoints:
#   ws://host:8765/ws/robot  — Pi agents connect here
#   ws://host:8765/ws/ui     — Browser connects here
#
# REST endpoints: see PLAN.md

import json
from pathlib import Path

import yaml
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from host.broker import broker
from host.fleet_manager import FleetManager

load_dotenv()

_FLEET_PATH = Path(__file__).parent.parent / "fleet.yaml"
_WEB_PATH   = Path(__file__).parent.parent / "web"


def _load_fleet() -> dict:
    with open(_FLEET_PATH) as f:
        return yaml.safe_load(f)


fleet        = _load_fleet()
fleet_manager = FleetManager(fleet)

app = FastAPI(title="botsim-v2")


# ---------------------------------------------------------------------------
# REST — fleet status
# ---------------------------------------------------------------------------

@app.get("/config")
async def get_config():
    return {
        "trajectory_cleanup_delay": fleet.get("trajectory_cleanup_delay", 3),
        "color_palette": fleet.get("color_palette", {}),
    }


@app.get("/robots")
async def get_robots():
    palette  = fleet.get("color_palette", {})
    fallback = list(palette.values())
    robots   = fleet["robots"]
    status   = broker.get_fleet_status(robots)
    for i, (r, s) in enumerate(zip(robots, status)):
        color_name = r.get("color")
        if color_name and color_name in palette:
            s["color"] = palette[color_name]
        elif fallback:
            s["color"] = fallback[i % len(fallback)]
        else:
            s["color"] = "#6366f1"
    return status


# ---------------------------------------------------------------------------
# REST — per-robot actions
# Note: literal routes (/deploy_all etc.) are registered before the
# parameterised route (/robots/{robot_id}/...) to avoid shadowing.
# ---------------------------------------------------------------------------

@app.post("/robots/deploy_all")
async def deploy_all():
    results = await fleet_manager.deploy_all()
    for r in results:
        await broker.broadcast_log(f"[{r['robot_id']}] deploy: {r['message']}")
    return results


@app.post("/robots/start_all")
async def start_all():
    results = await fleet_manager.start_all()
    for r in results:
        await broker.broadcast_log(f"[{r['robot_id']}] start: {r['message']}")
    return results


@app.post("/robots/stop_all")
async def stop_all():
    results = await fleet_manager.stop_all()
    for r in results:
        await broker.broadcast_log(f"[{r['robot_id']}] stop: {r['message']}")
    return results


@app.post("/robots/{robot_id}/deploy")
async def deploy_robot(robot_id: str):
    ok, msg = await fleet_manager.deploy(robot_id)
    await broker.broadcast_log(f"[{robot_id}] deploy: {msg}")
    return {"ok": ok, "message": msg}


@app.post("/robots/{robot_id}/start")
async def start_robot(robot_id: str):
    ok, msg = await fleet_manager.start(robot_id)
    await broker.broadcast_log(f"[{robot_id}] start: {msg}")
    return {"ok": ok, "message": msg}


@app.post("/robots/{robot_id}/stop")
async def stop_robot(robot_id: str):
    ok, msg = await fleet_manager.stop(robot_id)
    await broker.broadcast_log(f"[{robot_id}] stop: {msg}")
    return {"ok": ok, "message": msg}


# ---------------------------------------------------------------------------
# REST — algorithm
# ---------------------------------------------------------------------------

class AlgorithmRequest(BaseModel):
    name:   str
    params: dict = {}


@app.post("/algorithm")
async def set_algorithm(req: AlgorithmRequest):
    await broker.broadcast_algorithm(req.name, req.params)
    params_str = f" {req.params}" if req.params else ""
    await broker.broadcast_log(f"Algorithm → {req.name}{params_str}")
    return {"ok": True}


# ---------------------------------------------------------------------------
# WebSocket — Pi agents
# ---------------------------------------------------------------------------

@app.websocket("/ws/robot")
async def ws_robot(websocket: WebSocket):
    await websocket.accept()
    robot_id = None
    try:
        async for raw in websocket.iter_text():
            msg = json.loads(raw)
            if msg.get("type") == "hello":
                robot_id = msg["id"]
                broker.register_robot(robot_id, websocket)
                await broker.broadcast_log(f"[{robot_id}] connected")
            elif robot_id:
                await broker.handle_robot_message(robot_id, msg)
    except WebSocketDisconnect:
        pass
    finally:
        if robot_id:
            broker.unregister_robot(robot_id)
            await broker.broadcast_log(f"[{robot_id}] disconnected")
            await broker.broadcast_disconnect(robot_id)


# ---------------------------------------------------------------------------
# WebSocket — browser UI
# ---------------------------------------------------------------------------

@app.websocket("/ws/ui")
async def ws_ui(websocket: WebSocket):
    await websocket.accept()
    broker.register_ui(websocket)
    try:
        async for _ in websocket.iter_text():
            pass  # UI only listens; no inbound messages expected
    except WebSocketDisconnect:
        pass
    finally:
        broker.unregister_ui(websocket)


# Serve web/ at root — must be last so explicit routes above take priority
if _WEB_PATH.exists():
    app.mount("/", StaticFiles(directory=str(_WEB_PATH), html=True), name="web")
