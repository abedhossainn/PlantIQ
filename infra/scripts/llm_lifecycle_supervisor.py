#!/usr/bin/env python3
"""On-demand LLM container lifecycle supervisor.

Behavior:
- Watches a heartbeat file written by backend LLM requests.
- Starts compose service `llm` when a fresh demand signal appears and service is stopped.
- Stops compose service `llm` after configured idle timeout.

This script is intended to run on the host (where Docker CLI is available).
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


RUNNING = True


def _handle_shutdown(_sig: int, _frame) -> None:  # type: ignore[no-untyped-def]
    global RUNNING
    RUNNING = False


@dataclass
class Config:
    project_root: Path
    heartbeat_file: Path
    service_name: str
    poll_seconds: float
    idle_timeout_seconds: int
    request_window_seconds: int


class ComposeController:
    def __init__(self, project_root: Path):
        self.project_root = project_root

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["docker", "compose", *args],
            cwd=self.project_root,
            text=True,
            capture_output=True,
            check=False,
        )

    def is_service_running(self, service: str) -> bool:
        result = self._run(["ps", "--status", "running", "--services"])
        if result.returncode != 0:
            return False
        services = {line.strip() for line in result.stdout.splitlines() if line.strip()}
        return service in services

    def start_service(self, service: str) -> bool:
        result = self._run(["up", "-d", service])
        return result.returncode == 0

    def stop_service(self, service: str) -> bool:
        result = self._run(["stop", service])
        return result.returncode == 0


def parse_args() -> Config:
    parser = argparse.ArgumentParser(description="LLM container lifecycle supervisor")
    parser.add_argument(
        "--project-root",
        default=os.getenv("PLANTIQ_PROJECT_ROOT", "."),
        help="Path to repo root containing docker-compose.yml",
    )
    parser.add_argument(
        "--heartbeat-file",
        default=os.getenv("LLM_DEMAND_HEARTBEAT_FILE", "./data/artifacts/runtime/llm_last_used"),
        help="Backend-updated heartbeat path used as demand signal",
    )
    parser.add_argument("--service", default=os.getenv("LLM_SERVICE_NAME", "llm"))
    parser.add_argument("--poll-seconds", type=float, default=float(os.getenv("LLM_SUPERVISOR_POLL_SECONDS", "1.0")))
    parser.add_argument(
        "--idle-timeout-seconds",
        type=int,
        default=int(os.getenv("LLM_IDLE_TIMEOUT_SECONDS", "300")),
        help="Stop llm container when idle for this duration",
    )
    parser.add_argument(
        "--request-window-seconds",
        type=int,
        default=int(os.getenv("LLM_REQUEST_WINDOW_SECONDS", "30")),
        help="Fresh heartbeat age considered as startup demand",
    )

    args = parser.parse_args()
    project_root = Path(args.project_root).resolve()
    heartbeat_file = Path(args.heartbeat_file)
    if not heartbeat_file.is_absolute():
        heartbeat_file = (project_root / heartbeat_file).resolve()

    return Config(
        project_root=project_root,
        heartbeat_file=heartbeat_file,
        service_name=args.service,
        poll_seconds=max(0.2, float(args.poll_seconds)),
        idle_timeout_seconds=max(1, int(args.idle_timeout_seconds)),
        request_window_seconds=max(1, int(args.request_window_seconds)),
    )


def heartbeat_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return 0.0


def main() -> int:
    config = parse_args()

    signal.signal(signal.SIGINT, _handle_shutdown)
    signal.signal(signal.SIGTERM, _handle_shutdown)

    controller = ComposeController(config.project_root)
    last_seen_mtime = 0.0

    print(
        f"[llm-supervisor] started: service={config.service_name}, "
        f"heartbeat={config.heartbeat_file}, idle_timeout={config.idle_timeout_seconds}s"
    )

    while RUNNING:
        now = time.time()
        mtime = heartbeat_mtime(config.heartbeat_file)
        running = controller.is_service_running(config.service_name)

        if mtime > last_seen_mtime:
            last_seen_mtime = mtime

        # Start on fresh demand signal if service is currently stopped.
        if not running and mtime > 0 and (now - mtime) <= config.request_window_seconds:
            print("[llm-supervisor] demand signal detected; starting llm service")
            if not controller.start_service(config.service_name):
                print("[llm-supervisor] failed to start llm service", file=sys.stderr)

        # Stop when idle long enough.
        if running and mtime > 0 and (now - mtime) >= config.idle_timeout_seconds:
            print("[llm-supervisor] idle timeout reached; stopping llm service")
            if not controller.stop_service(config.service_name):
                print("[llm-supervisor] failed to stop llm service", file=sys.stderr)

        time.sleep(config.poll_seconds)

    print("[llm-supervisor] stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
