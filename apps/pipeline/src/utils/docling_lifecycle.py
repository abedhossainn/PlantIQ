"""
Docling on-demand lifecycle manager.

Controls the ``docling-serve`` Docker container lifecycle to prevent GPU
(VRAM) contention with the VLM image-description stage:

  - ``start()``: bring the container up and wait for its health endpoint.
  - ``stop()``: stop the container immediately to release GPU memory.

Honoring ``DOCLING_ON_DEMAND=true``:
  - When enabled: manages Docker container via the Engine API (unix socket).
  - When disabled: transparent no-op; safe for bare-metal / CI environments.
  - ``stop()`` never raises — failures are logged so operators can run
    ``make docling-down`` manually without masking extraction errors.

Docker Engine API is accessed via ``curl`` over the unix socket
(``/var/run/docker.sock``).  ``curl`` is already present in the backend
container; no additional Python packages are required.  The socket must be
bind-mounted into the container for full lifecycle control:

  volumes:
    - /var/run/docker.sock:/var/run/docker.sock
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_CONTAINER_NAME = "docling-serve"
_HEALTH_POLL_INTERVAL_SECONDS: float = 2.0
_DEFAULT_HEALTH_TIMEOUT_SECONDS: int = 120


def _docker_socket_path(environ: dict) -> Optional[str]:
    """Return the Docker unix-socket path if accessible, else ``None``."""
    docker_host = environ.get("DOCKER_HOST", "")
    if docker_host.startswith("unix://"):
        socket_path = docker_host[len("unix://"):]
    else:
        socket_path = "/var/run/docker.sock"
    return socket_path if Path(socket_path).exists() else None


def _curl_docker_post(path: str, socket_path: str, *, timeout: int = 30) -> int:
    """Issue a Docker Engine API POST via ``curl`` over a unix socket.

    Returns the ``curl`` exit code:

      - ``0``  → HTTP 2xx or 3xx (success / already in target state)
      - ``22`` → HTTP 4xx/5xx (Docker API error; ``--fail`` flag triggers this)
      - ``7``  → failed to connect (socket not accessible)
    """
    result = subprocess.run(
        [
            "curl",
            "--silent",
            "--fail",
            "--unix-socket", socket_path,
            "-X", "POST",
            f"http://localhost{path}",
        ],
        capture_output=True,
        timeout=timeout,
    )
    return result.returncode


class DoclingLifecycleManager:
    """Start/stop ``docling-serve`` on demand to prevent VRAM contention.

    Intended use — explicit start/stop with ``finally`` guarantee::

        lifecycle = DoclingLifecycleManager(docling_url=url)
        started = False
        try:
            lifecycle.start()
            started = True
            convert_pdf(...)          # Docling is healthy here
        finally:
            lifecycle.stop()          # always called; never raises

    Or as a context manager (stop on both success and exception)::

        with DoclingLifecycleManager(docling_url=url):
            convert_pdf(...)

    When ``DOCLING_ON_DEMAND`` is ``false`` (the default) the manager is a
    transparent no-op; all methods return immediately without side effects.
    """

    def __init__(
        self,
        *,
        docling_url: Optional[str] = None,
        environ: Optional[dict] = None,
        health_timeout_seconds: int = _DEFAULT_HEALTH_TIMEOUT_SECONDS,
    ) -> None:
        self._env: dict = dict(environ) if environ is not None else dict(os.environ)
        self._docling_url: str = (
            docling_url or self._env.get("DOCLING_URL", "http://localhost:5001")
        ).rstrip("/")
        self._on_demand: bool = (
            self._env.get("DOCLING_ON_DEMAND", "false").strip().lower() == "true"
        )
        self._health_timeout: int = health_timeout_seconds
        self._socket_path: Optional[str] = _docker_socket_path(self._env)

    # ------------------------------------------------------------------
    # Context manager protocol
    # ------------------------------------------------------------------

    def __enter__(self) -> "DoclingLifecycleManager":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_on_demand(self) -> bool:
        """``True`` when ``DOCLING_ON_DEMAND=true`` in the active environment."""
        return self._on_demand

    def start(self) -> None:
        """Bring ``docling-serve`` up and wait until its health endpoint responds.

        Raises ``RuntimeError`` if the Docker API call fails, or
        ``TimeoutError`` if Docling does not become healthy within
        ``health_timeout_seconds``.  Callers should treat both as fatal for
        the extraction stage (fail-fast, no retries).
        """
        if not self._on_demand:
            logger.debug(
                "[DoclingLifecycle] DOCLING_ON_DEMAND disabled — skipping start"
            )
            return

        if self._socket_path:
            logger.info(
                "[DoclingLifecycle] Starting %s via Docker Engine API (socket=%s)…",
                _CONTAINER_NAME,
                self._socket_path,
            )
            rc = _curl_docker_post(
                f"/containers/{_CONTAINER_NAME}/start",
                self._socket_path,
                timeout=60,
            )
            if rc != 0:
                raise RuntimeError(
                    f"[DoclingLifecycle] Docker Engine API failed to start "
                    f"{_CONTAINER_NAME} (curl exit code {rc}). "
                    "Ensure the container exists and the socket is accessible."
                )
        else:
            logger.warning(
                "[DoclingLifecycle] Docker socket not available — cannot start %s "
                "programmatically. Ensure it is already running, or bind-mount "
                "/var/run/docker.sock into this container.",
                _CONTAINER_NAME,
            )

        self._wait_healthy()
        logger.info("[DoclingLifecycle] %s is healthy and ready.", _CONTAINER_NAME)

    def stop(self) -> None:
        """Stop ``docling-serve`` to release GPU memory.

        This method **never raises**.  Stop failures are logged as errors
        so operators are informed to run ``make docling-down`` manually.
        This guarantee prevents a stop-side error from masking the original
        extraction result.
        """
        if not self._on_demand:
            logger.debug(
                "[DoclingLifecycle] DOCLING_ON_DEMAND disabled — skipping stop"
            )
            return

        if not self._socket_path:
            logger.warning(
                "[DoclingLifecycle] Docker socket not available — cannot stop %s; "
                "GPU memory may still be held. Run 'make docling-down' on the "
                "host to release VRAM.",
                _CONTAINER_NAME,
            )
            return

        logger.info(
            "[DoclingLifecycle] Stopping %s to release GPU memory…",
            _CONTAINER_NAME,
        )
        try:
            rc = _curl_docker_post(
                f"/containers/{_CONTAINER_NAME}/stop?t=10",
                self._socket_path,
                timeout=30,
            )
            if rc != 0:
                raise RuntimeError(
                    f"Docker Engine API failed to stop {_CONTAINER_NAME} "
                    f"(curl exit code {rc})."
                )
            logger.info(
                "[DoclingLifecycle] %s stopped; GPU memory released.",
                _CONTAINER_NAME,
            )
        except Exception as exc:
            logger.error(
                "[DoclingLifecycle] Failed to stop %s: %s — GPU memory may still "
                "be held. Run 'make docling-down' on the host to release VRAM.",
                _CONTAINER_NAME,
                exc,
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _wait_healthy(self) -> None:
        """Poll Docling's ``/health`` endpoint until it responds or timeout expires."""
        try:
            import requests as _requests
        except ImportError:
            logger.warning(
                "[DoclingLifecycle] 'requests' not importable; skipping health poll"
            )
            return

        url = f"{self._docling_url}/health"
        deadline = time.monotonic() + self._health_timeout
        last_err: Optional[Exception] = None

        while time.monotonic() < deadline:
            try:
                resp = _requests.get(url, timeout=5)
                if resp.status_code < 400:
                    return
            except Exception as exc:
                last_err = exc
            time.sleep(_HEALTH_POLL_INTERVAL_SECONDS)

        raise TimeoutError(
            f"[DoclingLifecycle] Timed out waiting for {_CONTAINER_NAME} at {url} "
            f"after {self._health_timeout}s."
            + (f" Last error: {last_err}" if last_err else "")
        )
