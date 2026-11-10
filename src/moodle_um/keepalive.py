"""Keep the Moodle session alive with a lightweight periodic ping.

Moodle's session timeout is two hours of inactivity. A request every few
minutes slides the expiry forward, so the saved session does not die
overnight. If the session has already expired, the normal bootstrap path
still tries a silent CAS renewal; if that fails, the user has to log in again.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from .client import connect
from .config import APP_DIR, ensure_app_dir

logger = logging.getLogger("moodle_um.keepalive")


def _log(message: str) -> None:
    ensure_app_dir()
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    line = f"{stamp} {message}"
    print(line, flush=True)
    log_path = APP_DIR / "keepalive.log"
    try:
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        log_path.chmod(0o600)
    except OSError:
        pass


async def ping_once() -> dict:
    """Perform one authenticated request so Moodle refreshes the session."""
    try:
        client = await connect()
        try:
            result = {
                "ok": True,
                "user_id": client.user_id,
                "user_name": client.user_name,
                "site": client.site,
            }
        finally:
            await client.close()
        _log(f"ok user={result['user_id']} ({result.get('user_name') or 'unknown'})")
        return result
    except Exception as exc:
        _log(f"ERROR {type(exc).__name__}: {exc}")
        raise


async def run_forever(interval: int = 600) -> None:
    """Ping forever; intended for a foreground service or a terminal."""
    _log(f"keepalive started (interval={interval}s)")
    while True:
        try:
            await ping_once()
        except Exception:
            # ping_once already logged the failure; keep the loop alive.
            pass
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            _log("keepalive stopped")
            raise
