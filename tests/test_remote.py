from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from moodle_um import remote
from moodle_um.config import Home


def test_token_resolution_uses_hashed_user_home(tmp_path, monkeypatch):
    home = Home(tmp_path / "u1")
    home.path.mkdir(parents=True)
    home.state_file.write_text("{}")

    monkeypatch.setattr(
        remote,
        "user_home",
        lambda digest: home
        if digest == remote._hash_token("secret-token")
        else Home(tmp_path / "missing"),
    )
    assert remote.resolve_token("secret-token") == home
    assert remote.resolve_token("wrong-token") is None


def test_mcp_requires_bearer_token(tmp_path, monkeypatch):
    home = Home(tmp_path / "u1")
    home.path.mkdir(parents=True)
    home.state_file.write_text("{}")
    monkeypatch.setattr(
        remote,
        "user_home",
        lambda digest: home
        if digest == remote._hash_token("secret-token")
        else Home(tmp_path / "missing"),
    )

    async def endpoint(request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/mcp", endpoint, methods=["POST"])])
    app.add_middleware(remote.TokenAuthMiddleware, protected_path="/mcp")
    client = TestClient(app)

    assert client.post("/mcp").status_code == 401
    assert client.post("/mcp", headers={"Authorization": "Bearer nope"}).status_code == 401
    good = client.post("/mcp", headers={"Authorization": "Bearer secret-token"})
    assert good.status_code == 200
    assert good.text == "ok"
