#!/usr/bin/env python3
# SSH / SFTP fleet management.
#
# Uses paramiko (same approach as shape-deployer) wrapped in
# asyncio.run_in_executor so FastAPI routes stay non-blocking.
#
# SSH password is read from SSH_PASSWORD env var (set via .env).
#
# deploy(robot_id):
#   SCP robot/ directory + fleet.yaml → ~/botsim/ on the Pi
# start(robot_id):
#   Flash lighthouse FPGA via SSH, then launch agent.py as background daemon
# stop(robot_id):
#   pkill agent.py on the Pi

import asyncio
import os
from pathlib import Path

import paramiko

_LOCAL_ROBOT_DIR = Path(__file__).parent.parent / "robot"
_LOCAL_FLEET_YAML = Path(__file__).parent.parent / "fleet.yaml"
_REMOTE_BOTSIM = "~/botsim"


# ---------------------------------------------------------------------------
# Blocking helpers (run in executor)
# ---------------------------------------------------------------------------

def _connect(host: str, user: str) -> paramiko.SSHClient:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        host,
        username=user,
        password=os.environ.get("SSH_PASSWORD", ""),
        allow_agent=False,
        look_for_keys=False,
        timeout=15,
    )
    return ssh


def _expand_home(ssh: paramiko.SSHClient) -> str:
    _, stdout, _ = ssh.exec_command("echo $HOME")
    return stdout.read().decode().strip()


def _sftp_ensure_dir(sftp, path: str):
    try:
        sftp.stat(path)
    except FileNotFoundError:
        sftp.mkdir(path)


def _deploy_sync(host: str, user: str) -> tuple[bool, str]:
    try:
        ssh = _connect(host, user)
        home = _expand_home(ssh)
        sftp = ssh.open_sftp()

        remote_botsim = home + "/botsim"
        remote_robot  = remote_botsim + "/robot"
        remote_algo   = remote_robot + "/algorithms"

        for d in [remote_botsim, remote_robot, remote_algo]:
            _sftp_ensure_dir(sftp, d)

        # Upload fleet.yaml
        sftp.put(str(_LOCAL_FLEET_YAML), remote_botsim + "/fleet.yaml")

        # Upload robot/ recursively (skip __pycache__)
        for f in _LOCAL_ROBOT_DIR.rglob("*"):
            if f.is_file() and "__pycache__" not in f.parts:
                rel = f.relative_to(_LOCAL_ROBOT_DIR)
                remote_file = remote_robot + "/" + rel.as_posix()
                sftp.put(str(f), remote_file)

        sftp.close()
        ssh.close()
        return True, "Deploy complete"
    except Exception as e:
        return False, str(e)


def _start_sync(host: str, user: str, fleet: dict) -> tuple[bool, str]:
    try:
        ssh = _connect(host, user)

        venv       = fleet["venv_path"]
        reboot     = fleet["reboot_script_path"]
        bootloader = fleet["bootloader_script_path"]
        lh_bin     = fleet["lighthouse_bin_path"]
        uart       = fleet["lighthouse_uart"]

        # Step 1: Flash lighthouse FPGA (blocking — must complete before agent starts)
        flash_cmd = (
            f"source {venv}/bin/activate && "
            f"python3 {reboot} {uart} && sleep 1 && "
            f"python3 {bootloader} {uart} {lh_bin}"
        )
        _, stdout, _ = ssh.exec_command(f"bash -c '{flash_cmd}' 2>&1")
        flash_out = stdout.read().decode().strip()

        # Step 2: Launch agent as background daemon
        agent_cmd = (
            f"source {venv}/bin/activate && "
            f"nohup python3 ~/botsim/robot/agent.py {uart} > /tmp/agent.log 2>&1 &"
        )
        ssh.exec_command(f"bash -c '{agent_cmd}'")

        ssh.close()
        return True, flash_out or "Started"
    except Exception as e:
        return False, str(e)


def _stop_sync(host: str, user: str) -> tuple[bool, str]:
    try:
        ssh = _connect(host, user)
        _, stdout, _ = ssh.exec_command("pkill -f agent.py")
        exit_code = stdout.channel.recv_exit_status()
        ssh.close()
        if exit_code == 0:
            return True, "Stopped"
        return True, "agent.py was not running"
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Async fleet manager
# ---------------------------------------------------------------------------

class FleetManager:
    def __init__(self, fleet: dict):
        self._fleet   = fleet
        self._robots  = {r["id"]: r for r in fleet["robots"]}

    async def deploy(self, robot_id: str) -> tuple[bool, str]:
        r = self._robots.get(robot_id)
        if not r:
            return False, f"Unknown robot: {robot_id}"
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _deploy_sync, r["host"], r["user"])

    async def start(self, robot_id: str) -> tuple[bool, str]:
        r = self._robots.get(robot_id)
        if not r:
            return False, f"Unknown robot: {robot_id}"
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _start_sync, r["host"], r["user"], self._fleet)

    async def stop(self, robot_id: str) -> tuple[bool, str]:
        r = self._robots.get(robot_id)
        if not r:
            return False, f"Unknown robot: {robot_id}"
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _stop_sync, r["host"], r["user"])

    async def deploy_all(self) -> list[dict]:
        results = await asyncio.gather(*[self.deploy(rid) for rid in self._robots])
        return [{"robot_id": rid, "ok": ok, "message": msg}
                for rid, (ok, msg) in zip(self._robots, results)]

    async def start_all(self) -> list[dict]:
        results = await asyncio.gather(*[self.start(rid) for rid in self._robots])
        return [{"robot_id": rid, "ok": ok, "message": msg}
                for rid, (ok, msg) in zip(self._robots, results)]

    async def stop_all(self) -> list[dict]:
        results = await asyncio.gather(*[self.stop(rid) for rid in self._robots])
        return [{"robot_id": rid, "ok": ok, "message": msg}
                for rid, (ok, msg) in zip(self._robots, results)]
