"""Configuration and on-disk state locations."""

from __future__ import annotations

import json
import os
from pathlib import Path

SITE_URL = os.environ.get("MOODLE_UM_SITE", "https://moodle.umontpellier.fr").rstrip("/")
LOGIN_URL = f"{SITE_URL}/login/index.php?authCAS=CAS"

APP_DIR = Path(
    os.environ.get("MOODLE_UM_HOME", Path.home() / ".config" / "moodle-um")
).expanduser()
PROFILE_DIR = APP_DIR / "browser_profile"
STATE_FILE = APP_DIR / "storage_state.json"
CONFIG_FILE = APP_DIR / "config.json"

# Where downloaded course files go by default.
DOWNLOADS_DIR = Path(
    os.environ.get("MOODLE_UM_DOWNLOADS", Path.home() / "Downloads" / "moodle-um")
).expanduser()

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def ensure_app_dir() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    try:
        APP_DIR.chmod(0o700)
    except OSError:
        pass


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_config(data: dict) -> None:
    ensure_app_dir()
    CONFIG_FILE.write_text(json.dumps(data, indent=2) + "\n")
    try:
        CONFIG_FILE.chmod(0o600)
    except OSError:
        pass


def get_site_url() -> str:
    env = os.environ.get("MOODLE_UM_SITE")
    if env:
        return env.rstrip("/")
    return load_config().get("site_url", SITE_URL).rstrip("/")
