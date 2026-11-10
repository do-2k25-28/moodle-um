"""ENT / CAS authentication via a real browser.

The university Moodle only accepts ENT (CAS) logins, often protected by MFA.
There is no password API, so we use Playwright once: the user signs in in a
normal browser window, and we keep the resulting cookies + a persistent
browser profile on disk.  Later calls reuse the session; if it expired but the
CAS session is still alive, a headless browser can silently renew it.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path

from .config import (
    PROFILE_DIR,
    STATE_FILE,
    USER_AGENT,
    ensure_app_dir,
    get_site_url,
    load_config,
    save_config,
)

LOGIN_TIMEOUT = int(os.environ.get("MOODLE_UM_LOGIN_TIMEOUT", "300"))


class AuthError(RuntimeError):
    """Raised when we cannot establish or restore a Moodle session."""


def find_browser() -> str | None:
    """Locate a Chromium/Chrome executable on the host."""
    env = os.environ.get("MOODLE_UM_BROWSER")
    if env:
        return env
    candidates = [
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
        "brave",
        "brave-browser",
        "microsoft-edge",
        "chrome",
    ]
    for name in candidates:
        path = shutil.which(name)
        if path:
            return path
    for path in (
        "/run/current-system/sw/bin/chromium",
        "/etc/profiles/per-user/"
        + os.environ.get("USER", "")
        + "/bin/google-chrome",
        "/usr/bin/chromium",
        "/usr/bin/google-chrome",
    ):
        if path and Path(path).exists():
            return path
    return None


def _launch_kwargs(headless: bool) -> dict:
    kwargs: dict = {
        "user_data_dir": str(PROFILE_DIR),
        "headless": headless,
        "args": [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
        ],
        "viewport": {"width": 1280, "height": 900},
    }
    exe = find_browser()
    if exe:
        kwargs["executable_path"] = exe
    return kwargs


async def _user_id(page) -> int:
    try:
        value = await page.evaluate(
            "() => (window.M && window.M.cfg && window.M.cfg.userId) || 0"
        )
        uid = int(value or 0)
        # Moodle's guest account is user id 1; it is not an authenticated user.
        return 0 if uid <= 1 else uid
    except Exception:
        return 0


async def _wait_for_login(page, timeout: float) -> bool:
    """Poll until a Moodle page reports a logged-in user."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if await _user_id(page):
            return True
        try:
            await page.wait_for_timeout(1000)
        except Exception:
            return False
    return False


def storage_exists() -> bool:
    return STATE_FILE.exists()


def load_storage_state() -> dict | None:
    if not STATE_FILE.exists():
        return None
    try:
        return json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def save_storage_state(state: dict) -> None:
    ensure_app_dir()
    STATE_FILE.write_text(json.dumps(state, indent=2))
    try:
        STATE_FILE.chmod(0o600)
    except OSError:
        pass


def session_cookies() -> list[dict]:
    """Return cookies usable against the Moodle site."""
    state = load_storage_state()
    if not state:
        return []
    site = get_site_url().split("//", 1)[-1].split("/", 1)[0]
    cookies = []
    for cookie in state.get("cookies", []):
        domain = (cookie.get("domain") or "").lstrip(".")
        if domain == site or domain.endswith(".umontpellier.fr") or site.endswith(domain):
            cookies.append(cookie)
    return cookies


def public_session_info() -> dict:
    cfg = load_config()
    return {
        "authenticated": bool(cfg.get("user_id")) and storage_exists(),
        "user_id": cfg.get("user_id"),
        "user_name": cfg.get("user_name"),
        "site_url": get_site_url(),
        "state_file": str(STATE_FILE),
    }


async def interactive_login(timeout: int = LOGIN_TIMEOUT) -> dict:
    """Open a visible browser and wait for the user to complete ENT login."""
    ensure_app_dir()
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        raise AuthError(
            "No graphical session detected (DISPLAY is unset). Run "
            "`moodle-um login` from a desktop terminal, or set up X11 "
            "forwarding."
        )

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(**_launch_kwargs(False))
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(
                f"{get_site_url()}/login/index.php?authCAS=CAS",
                wait_until="domcontentloaded",
                timeout=60000,
            )
            ok = await _wait_for_login(page, timeout)
            if not ok:
                raise AuthError(
                    "Login was not completed in time. If the window closed, "
                    "run `moodle-um login` again."
                )

            user_id = await _user_id(page)
            try:
                user_name = (
                    await page.locator("span.userinitials").first.get_attribute("title")
                ) or ""
            except Exception:
                user_name = ""
            if not user_name:
                try:
                    user_name = (
                        await page.locator(".logininfo a").first.inner_text()
                    ).strip()
                except Exception:
                    pass
            try:
                ua = await page.evaluate("() => navigator.userAgent")
            except Exception:
                ua = USER_AGENT

            state = await context.storage_state()
            save_storage_state(state)
            cfg = load_config()
            cfg.update(
                {
                    "site_url": get_site_url(),
                    "user_id": user_id,
                    "user_name": user_name,
                    "user_agent": ua,
                }
            )
            save_config(cfg)
            return {
                "user_id": user_id,
                "user_name": user_name,
                "site_url": get_site_url(),
            }
        finally:
            await context.close()


async def silent_refresh(timeout: float = 25) -> bool:
    """Try to renew the Moodle session using the still-valid CAS cookie."""
    if not storage_exists():
        return False
    from playwright.async_api import async_playwright

    ensure_app_dir()
    async with async_playwright() as p:
        browser = None
        try:
            browser = await p.chromium.launch(
                executable_path=find_browser(),
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = await browser.new_context(
                storage_state=str(STATE_FILE),
                user_agent=load_config().get("user_agent") or USER_AGENT,
                viewport={"width": 1280, "height": 900},
            )
            page = await context.new_page()
            await page.goto(
                f"{get_site_url()}/login/index.php?authCAS=CAS",
                wait_until="domcontentloaded",
                timeout=45000,
            )
            ok = await _wait_for_login(page, timeout)
            if not ok:
                return False
            state = await context.storage_state()
            save_storage_state(state)
            cfg = load_config()
            cfg["user_id"] = await _user_id(page)
            save_config(cfg)
            return True
        except Exception:
            return False
        finally:
            if browser is not None:
                try:
                    await browser.close()
                except Exception:
                    pass


async def ensure_session() -> None:
    """Raise AuthError if there is no usable saved session."""
    if not storage_exists():
        raise AuthError(
            "Not logged in. Run `moodle-um login` (or the `moodle_login` MCP "
            "tool) once to open the ENT login page."
        )
