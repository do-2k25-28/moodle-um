"""Multi-user onboarding and token auth for the remote MCP server.

The MCP transport itself is Streamable HTTP.  Each user uploads their own
``storage_state.json`` once, receives a personal bearer token, and Claude sends
that token in a request header.  The token selects a private session directory;
tools then run against that user's Moodle cookies.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import secrets
import shutil

import uvicorn
from starlette.requests import Request
from starlette.responses import HTMLResponse, Response
from starlette.routing import Route

from .client import MoodleClient
from .config import (
    Home,
    ensure_app_dir,
    get_site_url,
    load_config,
    save_config,
    user_home,
    users_dir,
)

MULTIUSER = os.environ.get("MOODLE_UM_MULTIUSER", "0") == "1"
MCP_PATH = os.environ.get("MOODLE_UM_MCP_PATH", "/mcp")
if not MCP_PATH.startswith("/"):
    MCP_PATH = "/" + MCP_PATH
CONNECT_PATH = MCP_PATH[:-4] + "/connect" if MCP_PATH.endswith("/mcp") else "/connect"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def resolve_token(token: str | None) -> Home | None:
    if not token:
        return None
    home = user_home(_hash_token(token))
    return home if home.state_file.exists() else None


def public_base_url() -> str:
    base = os.environ.get("MOODLE_UM_PUBLIC_URL")
    if base:
        return base.rstrip("/")
    host = os.environ.get("MOODLE_UM_MCP_HOST", "127.0.0.1")
    port = os.environ.get("MOODLE_UM_MCP_PORT", "8765")
    return f"http://{host}:{port}"


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 720px; margin: 3rem auto;
       padding: 0 1.2rem; line-height: 1.55; color: #1f2328; }}
code, pre {{ background: #f6f8fa; border-radius: 6px; }}
code {{ padding: .15rem .35rem; }}
pre {{ padding: 1rem; overflow-x: auto; }}
label {{ display: block; margin: 1.2rem 0 .4rem; font-weight: 600; }}
input[type=file] {{ padding: .6rem; border: 1px solid #d0d7de; border-radius: 6px; width: 100%; }}
button {{ margin-top: 1rem; padding: .7rem 1.2rem; border: 0; border-radius: 6px;
         background: #1f6feb; color: white; font-size: 1rem; cursor: pointer; }}
.note {{ background: #fff8c5; border: 1px solid #d4a72c; padding: .8rem 1rem; border-radius: 6px; }}
.token {{ background: #dafbe1; border: 1px solid #4ac26b; padding: 1rem; border-radius: 6px;
          word-break: break-all; }}
</style></head><body>{body}</body></html>"""


async def create_user_from_state(state_text: str) -> tuple[str, dict]:
    """Validate an uploaded browser state and store it as a new user."""
    if len(state_text.encode("utf-8")) > 2 * 1024 * 1024:
        raise ValueError("Session file is too large.")
    try:
        state = json.loads(state_text)
    except json.JSONDecodeError as exc:
        raise ValueError("That file is not valid JSON.") from exc
    if not isinstance(state, dict) or not state.get("cookies"):
        raise ValueError("That JSON does not contain a browser cookie list.")

    token = secrets.token_urlsafe(32)
    token_hash = _hash_token(token)
    base = users_dir()
    base.mkdir(parents=True, exist_ok=True)
    try:
        base.chmod(0o700)
    except OSError:
        pass

    temp = Home(base / f".tmp-{token_hash}")
    ensure_app_dir(temp)
    temp.state_file.write_text(json.dumps(state), encoding="utf-8")
    temp.state_file.chmod(0o600)

    client = MoodleClient(home=temp)
    try:
        await client.bootstrap()
        info = {
            "user_id": client.user_id,
            "user_name": client.user_name,
            "site": client.site,
        }
    except Exception:
        shutil.rmtree(temp.path, ignore_errors=True)
        raise
    finally:
        await client.close()

    final = user_home(token_hash)
    if final.path.exists():
        shutil.rmtree(final.path, ignore_errors=True)
    shutil.move(str(temp.path), str(final.path))
    cfg = load_config(final)
    cfg.update(
        {
            "site_url": get_site_url(final),
            "user_id": info["user_id"],
            "user_name": info["user_name"],
        }
    )
    save_config(cfg, final)
    return token, info


async def connect_endpoint(request: Request) -> Response:
    if request.method == "GET":
        body = """
<h1>Connect a Moodle account</h1>
<p>This server uses one Moodle session per person. Upload the session file
created by the CLI on your own machine:</p>
<pre>uv run moodle-um login
# then upload ~/.config/moodle-um/storage_state.json</pre>
<p>You will receive a personal token to paste into Claude's connector
<strong>Request headers</strong>:</p>
<pre>Authorization: Bearer &lt;token&gt;</pre>
<form method="post" enctype="multipart/form-data">
  <label for="state_file">storage_state.json</label>
  <input id="state_file" name="state_file" type="file"
         accept="application/json,.json" required>
  <button type="submit">Link this session</button>
</form>
<p class="note">The file contains Moodle session cookies, not your ENT password.
Keep the token secret; it grants access to this Moodle account until the
session expires.</p>
"""
        return HTMLResponse(_page("Connect Moodle", body))

    try:
        if request.headers.get("content-type", "").startswith("application/json"):
            raw = await request.body()
        else:
            form = await request.form()
            upload = form.get("state_file")
            if upload is None:
                raise ValueError("No session file was uploaded.")
            raw = await upload.read()
        token, info = await create_user_from_state(raw.decode("utf-8"))
    except Exception as exc:
        body = f"""<h1>Could not link this session</h1>
<p>{html.escape(str(exc))}</p>
<p><a href="{html.escape(CONNECT_PATH)}">Try again</a></p>"""
        return HTMLResponse(_page("Connect Moodle", body), status_code=400)

    body = f"""<h1>Moodle account linked</h1>
<p>Connected as <strong>{html.escape(info.get("user_name") or str(info.get("user_id")))}</strong>.</p>
<p>Add this header in Claude's connector settings (Request headers):</p>
<pre>Authorization: Bearer {html.escape(token)}</pre>
<p class="note">This token is shown once. Treat it like a password.</p>
"""
    return HTMLResponse(
        _page("Moodle connected", body),
        headers={"Cache-Control": "no-store"},
    )


class TokenAuthMiddleware:
    """Require a per-user bearer token for the MCP endpoint."""

    def __init__(self, app, protected_path: str = MCP_PATH) -> None:
        self.app = app
        self.protected_path = protected_path

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("path") != self.protected_path:
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        token = ""
        auth = headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
        if not token:
            token = headers.get("x-moodle-token", "").strip()

        home = resolve_token(token)
        if home is None:
            body = b'{"error":"missing_or_invalid_token"}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"www-authenticate", b"Bearer"),
                        (b"cache-control", b"no-store"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        reset = None
        try:
            from .config import set_current_home

            reset = set_current_home(home)
            await self.app(scope, receive, send)
        finally:
            if reset is not None:
                from .config import reset_current_home

                reset_current_home(reset)


def run_http() -> None:
    """Serve the MCP app plus the /connect onboarding page."""
    from .mcp_server import mcp

    app = mcp.streamable_http_app()
    app.router.routes.append(
        Route(CONNECT_PATH, endpoint=connect_endpoint, methods=["GET", "POST"])
    )
    if MULTIUSER:
        app.add_middleware(TokenAuthMiddleware, protected_path=MCP_PATH)

    uvicorn.run(
        app,
        host=os.environ.get("MOODLE_UM_MCP_HOST", "127.0.0.1"),
        port=int(os.environ.get("MOODLE_UM_MCP_PORT", "8765")),
        log_level="info",
    )
