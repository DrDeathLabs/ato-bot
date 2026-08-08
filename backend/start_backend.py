from __future__ import annotations

import os
import socket
import sys
import time
from urllib.parse import urlparse


def _log(message: str) -> None:
    print(f"[startup] {message}", flush=True)


def _wait_for_host(host: str, port: int, *, timeout_seconds: int = 90, interval_seconds: int = 2) -> None:
    deadline = time.time() + timeout_seconds
    last_error: str | None = None
    while time.time() < deadline:
        try:
            socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            with socket.create_connection((host, port), timeout=3):
                _log(f"Connected to {host}:{port}")
                return
        except OSError as exc:
            last_error = str(exc)
            _log(f"Waiting for {host}:{port} ({last_error})")
            time.sleep(interval_seconds)
    raise RuntimeError(f"Timed out waiting for {host}:{port}: {last_error or 'unknown error'}")


def main() -> int:
    database_url = os.environ.get("DATABASE_URL", "")
    redis_url = os.environ.get("REDIS_URL", "")

    if database_url:
        parsed_db = urlparse(database_url)
        if parsed_db.hostname and parsed_db.port:
            _wait_for_host(parsed_db.hostname, parsed_db.port)

    if redis_url:
        parsed_redis = urlparse(redis_url)
        if parsed_redis.hostname and parsed_redis.port:
            _wait_for_host(parsed_redis.hostname, parsed_redis.port)

    _log("Starting uvicorn")
    os.execvp(
        "uvicorn",
        ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"],
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - startup diagnostics
        _log(f"Fatal startup error: {exc}")
        raise
