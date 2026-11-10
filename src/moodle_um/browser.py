"""Generic headless-browser actions for pages without a dedicated tool.

This is the "do anything the web UI can do" escape hatch: fill a quiz, click a
button, upload a file, read a forum.  Every call is stateless — it starts a
headless Chromium with the saved Moodle cookies, performs the actions, and
returns the resulting page as text plus the interactive elements.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from . import auth
from .config import APP_DIR, USER_AGENT, get_site_url, load_config
from .parsers import html_to_text


class BrowserError(RuntimeError):
    pass


def _allowed(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "moodle.umontpellier.fr" or host.endswith(".umontpellier.fr")


async def _element_info(el) -> dict:
    tag = await el.evaluate("e => e.tagName.toLowerCase()")
    info: dict[str, Any] = {"tag": tag}
    for attr in ("name", "id", "type", "value", "placeholder", "href"):
        value = await el.get_attribute(attr)
        if value:
            info[attr] = value
    if tag in ("input", "textarea", "select"):
        # Find an associated label or aria-label.
        label = await el.get_attribute("aria-label")
        if not label:
            try:
                label = await el.evaluate(
                    """e => {
                        if (e.labels && e.labels.length) return e.labels[0].innerText;
                        const p = e.closest('label'); if (p) return p.innerText;
                        const g = e.closest('.form-group, .mb-3, .fitem, .que');
                        if (g) { const l = g.querySelector('label, .prompt, .qtext'); if (l) return l.innerText; }
                        return '';
                    }"""
                )
            except Exception:
                label = ""
        if label:
            info["label"] = " ".join(str(label).split())[:300]
    if tag == "select":
        try:
            options = []
            for o in await el.query_selector_all("option"):
                options.append(
                    {
                        "value": await o.get_attribute("value"),
                        "text": " ".join((await o.inner_text()).split()),
                    }
                )
            info["options"] = options
        except Exception:
            pass
    if tag in ("button", "a") and not info.get("value"):
        try:
            text = " ".join((await el.inner_text()).split())
            if text:
                info["text"] = text[:200]
        except Exception:
            pass
    return info


async def run_actions(
    url: str,
    actions: list[dict] | None = None,
    screenshot: bool = False,
    max_text: int = 15000,
) -> dict:
    actions = actions or []
    url = urljoin(get_site_url() + "/", url)
    if not _allowed(url):
        raise BrowserError(f"Refusing to browse non-university URL: {url}")

    from playwright.async_api import async_playwright

    exe = auth.find_browser()
    if not auth.storage_exists():
        raise auth.AuthError("Not logged in. Run `moodle-um login` first.")

    cfg = load_config()
    ua = cfg.get("user_agent") or USER_AGENT
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path=exe,
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            storage_state=str(auth.STATE_FILE),
            user_agent=ua,
            viewport={"width": 1400, "height": 1000},
            locale="fr-FR",
        )
        page = await context.new_page()
        page.set_default_timeout(20000)
        page.on("dialog", lambda dialog: asyncio.create_task(dialog.accept()))

        async def goto(target: str) -> None:
            await page.goto(target, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(400)

        try:
            await goto(url)
            if "cas.umontpellier.fr" in page.url:
                # Try a silent renewal once.
                if await auth.silent_refresh():
                    await context.close()
                    context = await browser.new_context(
                        storage_state=str(auth.STATE_FILE),
                        user_agent=ua,
                        viewport={"width": 1400, "height": 1000},
                        locale="fr-FR",
                    )
                    page = await context.new_page()
                    page.set_default_timeout(20000)
                    page.on(
                        "dialog", lambda dialog: asyncio.create_task(dialog.accept())
                    )
                    await goto(url)
                if "cas.umontpellier.fr" in page.url:
                    raise auth.AuthError(
                        "Moodle redirected to the ENT login page. Run "
                        "`moodle-um login` and retry."
                    )

            applied = []
            for index, action in enumerate(actions):
                kind = (action.get("type") or "").lower()
                selector = action.get("selector") or ""
                if kind in ("goto", "open"):
                    target = urljoin(page.url, action.get("url") or selector)
                    if not _allowed(target):
                        raise BrowserError(f"Refusing to navigate to {target}")
                    await goto(target)
                elif kind == "click":
                    if not selector:
                        raise BrowserError("click action requires a selector")
                    locator = page.locator(selector).first
                    await locator.click(timeout=20000)
                    await page.wait_for_timeout(500)
                elif kind == "fill":
                    locator = page.locator(selector).first
                    await locator.fill(str(action.get("value", "")))
                elif kind == "type":
                    locator = page.locator(selector).first
                    await locator.press_sequentially(str(action.get("value", "")))
                elif kind == "select":
                    locator = page.locator(selector).first
                    await locator.select_option(str(action.get("value", "")))
                elif kind == "check":
                    await page.locator(selector).first.check()
                elif kind == "uncheck":
                    await page.locator(selector).first.uncheck()
                elif kind == "press":
                    await page.keyboard.press(str(action.get("value", "Enter")))
                elif kind == "set_file":
                    path = Path(str(action.get("value", ""))).expanduser()
                    if not path.is_file():
                        raise BrowserError(f"File not found: {path}")
                    await page.locator(selector).first.set_input_files(str(path))
                elif kind == "wait":
                    await page.wait_for_timeout(int(action.get("value", 1000)))
                elif kind == "wait_for":
                    await page.wait_for_selector(selector, timeout=30000)
                elif kind == "scroll":
                    await page.mouse.wheel(0, int(action.get("value", 800)))
                else:
                    raise BrowserError(f"Unknown action type: {kind}")
                applied.append({"index": index, "type": kind, "url": page.url})
                if len(context.pages) > 1:
                    page = context.pages[-1]

            try:
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                pass

            title = await page.title()
            text = html_to_text(await page.content(), page.url)
            elements = []
            for selector in ("input", "textarea", "select", "button"):
                for el in await page.query_selector_all(selector):
                    try:
                        visible = await el.is_visible()
                        if not visible and await el.get_attribute("type") != "file":
                            continue
                        elements.append(await _element_info(el))
                    except Exception:
                        continue

            result: dict[str, Any] = {
                "url": page.url,
                "title": title,
                "text": text[:max_text],
                "elements": elements[:200],
                "actions_applied": applied,
            }
            if screenshot:
                out_dir = APP_DIR / "screenshots"
                out_dir.mkdir(parents=True, exist_ok=True)
                shot = out_dir / f"page-{int(time.time())}.png"
                await page.screenshot(path=str(shot), full_page=False)
                result["screenshot"] = str(shot)
            return result
        except BrowserError:
            raise
        except Exception as exc:
            raise BrowserError(f"Browser action failed: {exc}") from exc
        finally:
            await context.close()
            await browser.close()
