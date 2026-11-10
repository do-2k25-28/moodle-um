"""Configuration, per-user homes, and on-disk state locations."""

from __future__ import annotations

import json
import os
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

SITE_URL = os.environ.get("MOODLE_UM_SITE", "https://moodle.umontpellier.fr").rstrip("/")
LOGIN_URL = f"{SITE_URL}/login/index.php?authCAS=CAS"

APP_DIR = Path(
    os.environ.get("MOODLE_UM_HOME", Path.home() / ".config" / "moodle-um")
).expanduser()


@dataclass(frozen=True)
class Home:
    """One Moodle session's private directory."""

    path: Path

    @property
    def state_file(self) -> Path:
        return self.path / "storage_state.json"

    @property
    def config_file(self) -> Path:
        return self.path / "config.json"

    @property
    def browser_profile(self) -> Path:
        return self.path / "browser_profile"


DEFAULT_HOME = Home(APP_DIR)
_current_home: ContextVar[Home] = ContextVar("moodle_home", default=DEFAULT_HOME)


def current_home() -> Home:
    return _current_home.get()


def set_current_home(home: Home):
    return _current_home.set(home)


def reset_current_home(token) -> None:
    _current_home.reset(token)


def users_dir() -> Path:
    return APP_DIR / "users"


def user_home(token_hash: str) -> Home:
    return Home(users_dir() / token_hash)


# Backwards-compatible default paths.
PROFILE_DIR = DEFAULT_HOME.browser_profile
STATE_FILE = DEFAULT_HOME.state_file
CONFIG_FILE = DEFAULT_HOME.config_file

# Where downloaded course files go by default.
DOWNLOADS_DIR = Path(
    os.environ.get("MOODLE_UM_DOWNLOADS", Path.home() / "Downloads" / "moodle-um")
).expanduser()

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def ensure_app_dir(home: Home | None = None) -> None:
    target = (home or current_home()).path
    target.mkdir(parents=True, exist_ok=True)
    try:
        target.chmod(0o700)
    except OSError:
        pass


def load_config(home: Home | None = None) -> dict:
    path = (home or current_home()).config_file
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_config(data: dict, home: Home | None = None) -> None:
    target = home or current_home()
    ensure_app_dir(target)
    target.config_file.write_text(json.dumps(data, indent=2) + "\n")
    try:
        target.config_file.chmod(0o600)
    except OSError:
        pass


def get_site_url(home: Home | None = None) -> str:
    env = os.environ.get("MOODLE_UM_SITE")
    if env:
        return env.rstrip("/")
    return load_config(home).get("site_url", SITE_URL).rstrip("/")
