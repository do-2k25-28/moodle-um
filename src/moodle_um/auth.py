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
    USER_AGENT,
    Home,
    current_home,
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


def _launch_kwargs(headless: bool, home: Home) -> dict:
    kwargs: dict = {
        "user_data_dir": str(home.browser_profile),
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


def storage_exists(home: Home | None = None) -> bool:
    return (home or current_home()).state_file.exists()


def load_storage_state(home: Home | None = None) -> dict | None:
    target = (home or current_home()).state_file
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def save_storage_state(state: dict, home: Home | None = None) -> None:
    target = home or current_home()
    ensure_app_dir(target)
    target.state_file.write_text(json.dumps(state, indent=2))
    try:
        target.state_file.chmod(0o600)
    except OSError:
        pass


def session_cookies(home: Home | None = None) -> list[dict]:
    """Return cookies usable against the Moodle site."""
    target = home or current_home()
    state = load_storage_state(target)
    if not state:
        return []
    site = get_site_url(target).split("//", 1)[-1].split("/", 1)[0]
    cookies = []
    for cookie in state.get("cookies", []):
        domain = (cookie.get("domain") or "").lstrip(".")
        if domain == site or domain.endswith(".umontpellier.fr") or site.endswith(domain):
            cookies.append(cookie)
    return cookies


def public_session_info(home: Home | None = None) -> dict:
    target = home or current_home()
    cfg = load_config(target)
    return {
        "authenticated": bool(cfg.get("user_id")) and storage_exists(target),
        "user_id": cfg.get("user_id"),
        "user_name": cfg.get("user_name"),
        "site_url": get_site_url(target),
        "state_file": str(target.state_file),
    }


async def interactive_login(
    timeout: int = LOGIN_TIMEOUT, home: Home | None = None
) -> dict:
    """Open a visible browser and wait for the user to complete ENT login."""
    target = home or current_home()
    ensure_app_dir(target)
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        raise AuthError(
            "No graphical session detected (DISPLAY is unset). Run "
            "`moodle-um login` from a desktop terminal, or set up X11 "
            "forwarding."
        )

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            **_launch_kwargs(False, target)
        )
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(
                f"{get_site_url(target)}/login/index.php?authCAS=CAS",
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
            save_storage_state(state, target)
            cfg = load_config(target)
            cfg.update(
                {
                    "site_url": get_site_url(target),
                    "user_id": user_id,
                    "user_name": user_name,
                    "user_agent": ua,
                }
            )
            save_config(cfg, target)
            return {
                "user_id": user_id,
                "user_name": user_name,
                "site_url": get_site_url(target),
            }
        finally:
            await context.close()


async def silent_refresh(timeout: float = 25, home: Home | None = None) -> bool:
    """Try to renew the Moodle session using the still-valid CAS cookie."""
    target = home or current_home()
    if not storage_exists(target):
        return False
    from playwright.async_api import async_playwright

    ensure_app_dir(target)
    async with async_playwright() as p:
        browser = None
        try:
            browser = await p.chromium.launch(
                executable_path=find_browser(),
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = await browser.new_context(
                storage_state=str(target.state_file),
                user_agent=load_config(target).get("user_agent") or USER_AGENT,
                viewport={"width": 1280, "height": 900},
            )
            page = await context.new_page()
            await page.goto(
                f"{get_site_url(target)}/login/index.php?authCAS=CAS",
                wait_until="domcontentloaded",
                timeout=45000,
            )
            ok = await _wait_for_login(page, timeout)
            if not ok:
                return False
            state = await context.storage_state()
            save_storage_state(state, target)
            cfg = load_config(target)
            cfg["user_id"] = await _user_id(page)
            save_config(cfg, target)
            return True
        except Exception:
            return False
        finally:
            if browser is not None:
                try:
                    await browser.close()
                except Exception:
                    pass


async def ensure_session(home: Home | None = None) -> None:
    """Raise AuthError if there is no usable saved session."""
    if not storage_exists(home):
        raise AuthError(
            "Not logged in. Run `moodle-um login` (or the `moodle_login` MCP "
            "tool) once to open the ENT login page."
        )
