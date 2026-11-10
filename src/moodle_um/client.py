"""Low-level HTTP client for a logged-in Moodle session."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

import httpx

from . import auth
from .config import (
    DOWNLOADS_DIR,
    USER_AGENT,
    Home,
    current_home,
    get_site_url,
    load_config,
    save_config,
)


class MoodleError(RuntimeError):
    def __init__(self, message: str, errorcode: str | None = None):
        super().__init__(message)
        self.errorcode = errorcode


def extract_moodle_cfg(html: str) -> dict:
    """Extract the `M.cfg = {...};` JSON object from a Moodle page."""
    match = re.search(r"M\.cfg\s*=\s*", html)
    if not match:
        return {}
    start = html.find("{", match.end())
    if start == -1:
        return {}
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(html)):
        ch = html[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                raw = html[start : i + 1]
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return {}
    return {}


def cookies_to_httpx(cookies: list[dict]) -> httpx.Cookies:
    jar = httpx.Cookies()
    for cookie in cookies:
        name = cookie.get("name")
        value = cookie.get("value")
        if not name or value is None:
            continue
        jar.set(
            name,
            value,
            domain=cookie.get("domain") or None,
            path=cookie.get("path") or "/",
        )
    return jar


class MoodleClient:
    """Cookie-authenticated client.

    Instantiate with :meth:`connect` which validates/refreshes the session.
    """

    def __init__(self, home: Home | None = None) -> None:
        self.home = home or current_home()
        self.site = get_site_url(self.home)
        self.sesskey: str = ""
        self.user_id: int = 0
        self.user_name: str = ""
        self.http = self._new_http()
        self._bootstrapped = False

    def _new_http(self) -> httpx.AsyncClient:
        cfg = load_config(self.home)
        ua = cfg.get("user_agent") or USER_AGENT
        jar = cookies_to_httpx(auth.session_cookies(self.home))
        return httpx.AsyncClient(
            cookies=jar,
            follow_redirects=True,
            timeout=httpx.Timeout(30.0, read=120.0),
            headers={
                "User-Agent": ua,
                "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.6",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )

    async def close(self) -> None:
        await self.http.aclose()

    # ------------------------------------------------------------------ URLs
    def url(self, path_or_url: str) -> str:
        if path_or_url.startswith(("http://", "https://")):
            return path_or_url
        return urljoin(self.site + "/", path_or_url.lstrip("/"))

    def _allowed(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        site_host = urlparse(self.site).hostname or ""
        return host == site_host or host.endswith(".umontpellier.fr")

    # --------------------------------------------------------------- session
    async def bootstrap(self) -> None:
        if not auth.storage_exists(self.home):
            raise auth.AuthError(
                "Not logged in. Run `moodle-um login` (or the `moodle_login` MCP "
                "tool) once to open the ENT login page."
            )
        html, _final_url = await self._get_text("/my/")
        cfg = extract_moodle_cfg(html)
        if int(cfg.get("userId") or 0) <= 1:
            if await auth.silent_refresh(home=self.home):
                await self._reload_session()
                html, _final_url = await self._get_text("/my/")
                cfg = extract_moodle_cfg(html)
            if int(cfg.get("userId") or 0) <= 1:
                raise auth.AuthError(
                    "Your Moodle session expired and could not be renewed. "
                    "Run `moodle-um login` (or the `moodle_login` MCP tool) "
                    "to sign in again through ENT."
                )
        self.user_id = int(cfg.get("userId") or 0)
        if self.user_id <= 1:
            self.user_id = 0
        self.sesskey = str(cfg.get("sesskey") or "")
        if not self.user_name:
            self.user_name = self._parse_user_name(html)
        self._bootstrapped = True
        if self.user_name:
            cfg = load_config(self.home)
            if cfg.get("user_name") != self.user_name or cfg.get("user_id") != self.user_id:
                cfg["user_name"] = self.user_name
                cfg["user_id"] = self.user_id
                save_config(cfg, self.home)
        self._persist_cookies()

    async def _reload_session(self) -> None:
        await self.http.aclose()
        self.http = self._new_http()

    @staticmethod
    def _parse_user_name(html: str) -> str:
        match = re.search(
            r'<span class="userinitials[^"]*"[^>]*title="([^"]+)"', html
        )
        if match:
            return match.group(1).strip()
        match = re.search(
            r'class="logininfo"[^>]*>.*?<a[^>]*>(.*?)</a>', html, re.DOTALL
        )
        if match:
            return re.sub(r"<[^>]+>", "", match.group(1)).strip()
        return ""

    def _persist_cookies(self) -> None:
        """Copy cookies set during HTTP calls back to the saved state."""
        state = auth.load_storage_state(self.home)
        if not state:
            return
        existing = {
            (c.get("name"), c.get("domain"), c.get("path")): c
            for c in state.get("cookies", [])
        }
        for cookie in self.http.cookies.jar:
            key = (cookie.name, cookie.domain, cookie.path)
            entry = existing.get(key)
            if entry is None:
                entry = {
                    "name": cookie.name,
                    "value": cookie.value,
                    "domain": cookie.domain,
                    "path": cookie.path,
                    "expires": cookie.expires or -1,
                    "httpOnly": False,
                    "secure": bool(cookie.secure),
                    "sameSite": "Lax",
                }
                state.setdefault("cookies", []).append(entry)
                existing[key] = entry
            entry["value"] = cookie.value
        auth.save_storage_state(state, self.home)

    async def ensure(self) -> None:
        if not self._bootstrapped:
            await self.bootstrap()

    # ----------------------------------------------------------------- HTTP
    async def _get_text(self, path_or_url: str, **kwargs) -> tuple[str, str]:
        url = self.url(path_or_url)
        if not self._allowed(url):
            raise MoodleError(f"Refusing to request non-university URL: {url}")
        response = await self.http.get(url, **kwargs)
        return response.text, str(response.url)

    async def fetch(self, path_or_url: str) -> httpx.Response:
        """GET any university URL, following redirects, with session auth."""
        await self.ensure()
        url = self.url(path_or_url)
        if not self._allowed(url):
            raise MoodleError(f"Refusing to request non-university URL: {url}")
        response = await self.http.get(url)
        if response.status_code >= 400:
            raise MoodleError(
                f"HTTP {response.status_code} while fetching {response.url}"
            )
        return response

    async def get_text(self, path_or_url: str) -> tuple[str, str]:
        await self.ensure()
        html, final_url = await self._get_text(path_or_url)
        if self._is_login_redirect(final_url, html):
            if await auth.silent_refresh(home=self.home):
                await self._reload_session()
                await self.bootstrap()
                html, final_url = await self._get_text(path_or_url)
            if self._is_login_redirect(final_url, html):
                raise auth.AuthError(
                    "Moodle redirected to the login page. Run `moodle-um login`."
                )
        return html, final_url

    @staticmethod
    def _is_login_redirect(final_url: str, html: str) -> bool:
        if re.search(r"/login/(index\.php)?(\?|$)", final_url) and "authCAS" not in final_url:
            return True
        cfg = extract_moodle_cfg(html)
        return bool(cfg) and int(cfg.get("userId") or 0) <= 1

    async def ajax(self, methodname: str, args: dict | None = None) -> Any:
        """Call a Moodle AJAX external function (lib/ajax/service.php)."""
        await self.ensure()
        payload = [{"index": 0, "methodname": methodname, "args": args or {}}]
        params = {"sesskey": self.sesskey, "info": methodname}
        response = await self.http.post(
            self.url("/lib/ajax/service.php"),
            params=params,
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            data = response.json()
        except json.JSONDecodeError:
            raise MoodleError(
                f"Unexpected non-JSON response from Moodle ({response.status_code})"
            )
        if isinstance(data, dict) and data.get("errorcode") == "invalidsesskey":
            await self.bootstrap()
            return await self.ajax(methodname, args)
        if not isinstance(data, list) or not data:
            raise MoodleError(f"Unexpected AJAX response: {str(data)[:300]}")
        item = data[0]
        if item.get("error"):
            exc = item.get("exception") or {}
            raise MoodleError(
                f"{methodname}: {exc.get('message') or 'unknown error'}",
                exc.get("errorcode"),
            )
        return item.get("data")

    async def post_form(
        self,
        path_or_url: str,
        data: dict[str, Any],
        files: dict[str, Any] | None = None,
    ) -> tuple[str, str]:
        await self.ensure()
        url = self.url(path_or_url)
        if not self._allowed(url):
            raise MoodleError(f"Refusing to post to non-university URL: {url}")
        payload = dict(data)
        payload.setdefault("sesskey", self.sesskey)
        response = await self.http.post(
            url,
            data=payload,
            files=files,
            headers={"Referer": self.url("/my/")},
        )
        return response.text, str(response.url)

    # -------------------------------------------------------------- downloads
    async def download(
        self, path_or_url: str, dest: str | Path | None = None
    ) -> dict[str, Any]:
        await self.ensure()
        url = self.url(path_or_url)
        if not self._allowed(url):
            raise MoodleError(f"Refusing to download from non-university URL: {url}")

        async with self.http.stream("GET", url) as response:
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if content_type.startswith("text/html"):
                body = (await response.aread()).decode("utf-8", "replace")
                if "login" in body.lower() or "error" in body.lower():
                    raise MoodleError(
                        "The download returned an HTML page (session expired or "
                        "access denied)."
                    )
                raise MoodleError("The URL returned an HTML page, not a file.")

            filename = None
            disposition = response.headers.get("content-disposition", "")
            match = re.search(r"filename\*?=(?:UTF-8''|\")?([^\";]+)", disposition)
            if match:
                from urllib.parse import unquote

                filename = unquote(match.group(1).strip())
            if not filename:
                filename = self._guess_filename(str(response.url))
            if dest is None:
                dest_path = DOWNLOADS_DIR / filename
            else:
                dest_path = Path(dest).expanduser()
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            if dest_path.exists():
                stem, suffix = dest_path.stem, dest_path.suffix
                counter = 2
                while dest_path.exists():
                    dest_path = dest_path.with_name(f"{stem}-{counter}{suffix}")
                    counter += 1

            with dest_path.open("wb") as fh:
                async for chunk in response.aiter_bytes():
                    fh.write(chunk)

        return {
            "path": str(dest_path),
            "bytes": dest_path.stat().st_size,
            "content_type": content_type,
            "url": str(response.url),
        }

    @staticmethod
    def _guess_filename(url: str) -> str:
        name = unquote(urlparse(url).path.rsplit("/", 1)[-1])
        name = re.sub(r"[^A-Za-z0-9._ ()\-]", "_", name).strip() or "download"
        return name

    # ---------------------------------------------------------------- helpers
    async def pluginfile_url(self, fileurl: str) -> str:
        """Return a browser-downloadable pluginfile URL."""
        url = self.url(fileurl)
        # Moodle accepts the session cookie directly for pluginfile.php.
        return url


async def connect(home: Home | None = None) -> MoodleClient:
    client = MoodleClient(home=home)
    await client.bootstrap()
    return client
