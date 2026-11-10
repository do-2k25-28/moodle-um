"""Typer command line interface."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import typer

from . import auth, browser, services
from . import quiz as quiz_service
from .client import MoodleError, connect
from .config import APP_DIR

app = typer.Typer(
    add_completion=False,
    help="Moodle Université de Montpellier — CLI (and MCP server).",
    no_args_is_help=True,
)


def _run(coro):
    try:
        return asyncio.run(coro)
    except auth.AuthError as exc:
        typer.secho(f"Auth error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)
    except MoodleError as exc:
        typer.secho(f"Moodle error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    except browser.BrowserError as exc:
        typer.secho(f"Browser error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    except KeyboardInterrupt:
        raise typer.Exit(130)


def _print_json(data) -> None:
    typer.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))


@app.command()
def login() -> None:
    """Open the ENT login page and save the session."""
    typer.echo("Opening the ENT login page in Chromium…")
    typer.echo("Sign in with your ENT identifiant (and MFA). The window closes by itself.")
    info = _run(auth.interactive_login())
    typer.secho(
        f"Logged in as {info.get('user_name') or info['user_id']} "
        f"(user id {info['user_id']}).",
        fg=typer.colors.GREEN,
    )
    typer.echo(f"Session saved in {APP_DIR}")


@app.command()
def logout() -> None:
    """Delete the saved session (does not log out of CAS)."""
    from .config import STATE_FILE

    if STATE_FILE.exists():
        STATE_FILE.unlink()
    typer.echo("Saved Moodle session deleted.")


@app.command()
def status() -> None:
    """Show the current login status."""

    async def _status():
        client = await connect()
        try:
            return {
                "site": client.site,
                "user_id": client.user_id,
                "user_name": client.user_name,
                "sesskey": client.sesskey,
            }
        finally:
            await client.close()

    _print_json(_run(_status()))


@app.command()
def courses(
    query: str = typer.Option(None, "--query", "-q", help="Filter by name or shortname"),
    as_json: bool = typer.Option(False, "--json", help="Print JSON"),
) -> None:
    """List your enrolled courses."""

    async def _courses():
        client = await connect()
        try:
            return await services.list_courses(client, query)
        finally:
            await client.close()

    data = _run(_courses())
    if as_json:
        _print_json(data)
        return
    for course in data:
        typer.echo(f"{course['id']:>7}  {course['name']}")


@app.command()
def course(
    courseid: int = typer.Argument(..., help="Moodle course id"),
    as_json: bool = typer.Option(False, "--json", help="Print JSON"),
) -> None:
    """Show a course's sections and activities."""

    async def _course():
        client = await connect()
        try:
            return await services.get_course(client, courseid)
        finally:
            await client.close()

    data = _run(_course())
    if as_json:
        _print_json(data)
        return
    typer.secho(data["name"], bold=True)
    for section in data["sections"]:
        typer.secho(f"\n## {section['name']}", fg=typer.colors.CYAN)
        for activity in section["activities"]:
            typer.echo(
                f"  [{activity['modname'] or '?'}] {activity['name']}  (cmid {activity['cmid']})"
            )
            if activity["url"]:
                typer.secho(f"      {activity['url']}", fg=typer.colors.BRIGHT_BLACK)


@app.command()
def assignments(
    courseid: int = typer.Argument(..., help="Moodle course id"),
    as_json: bool = typer.Option(False, "--json", help="Print JSON"),
) -> None:
    """List a course's assignments and submission status."""

    async def _assignments():
        client = await connect()
        try:
            return await services.list_assignments(client, courseid)
        finally:
            await client.close()

    data = _run(_assignments())
    if as_json:
        _print_json(data)
        return
    for item in data:
        typer.echo(
            f"{item['cmid']:>8}  {item['name']}\n          due: {item.get('due') or '-'}  |  {item.get('submission') or 'no submission'}"
        )


@app.command()
def assignment(
    cmid: int = typer.Argument(..., help="course-module id"),
    as_json: bool = typer.Option(False, "--json", help="Print JSON"),
) -> None:
    """Show one assignment's instructions and submission status."""

    async def _assignment():
        client = await connect()
        try:
            return await services.get_assignment(client, cmid)
        finally:
            await client.close()

    data = _run(_assignment())
    if as_json:
        _print_json(data)
        return
    typer.secho(data["name"], bold=True)
    typer.echo(f"  due: {data.get('due') or '-'}")
    typer.echo(f"  status: {data.get('status', '')}")
    if data.get("intro"):
        typer.echo("\n" + data["intro"])
    if data.get("edit_submission_url"):
        typer.echo(f"\nSubmission form: {data['edit_submission_url']}")


@app.command()
def quizzes(courseid: int = typer.Argument(...)) -> None:
    """List a course's quizzes."""

    async def _quizzes():
        client = await connect()
        try:
            return await services.list_quizzes(client, courseid)
        finally:
            await client.close()

    _print_json(_run(_quizzes()))


@app.command()
def quiz(cmid: int = typer.Argument(...)) -> None:
    """Show a quiz and its attempts."""

    async def _quiz():
        client = await connect()
        try:
            return await services.get_quiz(client, cmid)
        finally:
            await client.close()

    _print_json(_run(_quiz()))


@app.command("quiz-start")
def quiz_start(cmid: int = typer.Argument(..., help="course-module id")) -> None:
    """Start/resume a quiz attempt and print its questions and choices."""

    async def _quiz_start():
        client = await connect()
        try:
            return await quiz_service.start_quiz(client, cmid)
        finally:
            await client.close()

    _print_json(_run(_quiz_start()))


@app.command("quiz-attempt")
def quiz_attempt(
    attemptid: int = typer.Argument(..., help="quiz attempt id"),
    page: int = typer.Option(0, "--page", "-p", help="zero-based page number"),
) -> None:
    """Read one page of an in-progress quiz attempt."""

    async def _quiz_attempt():
        client = await connect()
        try:
            return await quiz_service.get_attempt(client, attemptid, page)
        finally:
            await client.close()

    _print_json(_run(_quiz_attempt()))


@app.command("quiz-solve")
def quiz_solve(
    attemptid: int = typer.Argument(..., help="quiz attempt id"),
    answers: str = typer.Option(
        ..., "--answers", help='JSON map, e.g. \'{"1":"b","2":"Paris"}\''
    ),
    page: int = typer.Option(None, "--page", "-p", help="zero-based page number"),
) -> None:
    """Save answers for one quiz page (does not submit)."""
    parsed = json.loads(answers)

    async def _solve():
        client = await connect()
        try:
            return await quiz_service.solve_attempt(client, attemptid, parsed, page)
        finally:
            await client.close()

    _print_json(_run(_solve()))


@app.command("quiz-submit")
def quiz_submit(
    attemptid: int = typer.Argument(..., help="quiz attempt id"),
    page: int = typer.Option(None, "--page", "-p", help="zero-based page number"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Confirm final submission"),
) -> None:
    """Submit a quiz attempt (irreversible)."""
    if not yes:
        typer.secho("Refusing without --yes.", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(1)

    async def _submit():
        client = await connect()
        try:
            return await quiz_service.submit_attempt(client, attemptid, page)
        finally:
            await client.close()

    _print_json(_run(_submit()))


@app.command()
def grades(courseid: int = typer.Argument(...)) -> None:
    """Show your grade report for a course."""

    async def _grades():
        client = await connect()
        try:
            return await services.get_grades(client, courseid)
        finally:
            await client.close()

    _print_json(_run(_grades()))


@app.command()
def upcoming(limit: int = typer.Option(30, "--limit", "-n")) -> None:
    """Show upcoming deadlines and calendar events."""

    async def _upcoming():
        client = await connect()
        try:
            return await services.upcoming(client, limit)
        finally:
            await client.close()

    _print_json(_run(_upcoming()))


@app.command()
def submit(
    cmid: int = typer.Argument(..., help="course-module id of the assignment"),
    text: str = typer.Option(None, "--text", help="Online text to submit"),
    file: list[Path] = typer.Option(None, "--file", "-f", help="File to upload (repeatable)"),
    no_submit: bool = typer.Option(
        False, "--no-submit", help="Save without clicking 'Submit for grading'"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Confirm the submission"),
) -> None:
    """Submit an assignment (online text and/or files)."""
    if not yes:
        typer.secho(
            "Refusing to submit without --yes. This action is final and may be graded.",
            fg=typer.colors.YELLOW,
            err=True,
        )
        raise typer.Exit(1)
    if not text and not file:
        typer.secho("Nothing to submit: pass --text and/or --file.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    async def _submit():
        client = await connect()
        try:
            return await services.submit_assignment(
                client,
                cmid=cmid,
                text=text,
                files=[str(p) for p in (file or [])],
                submit_for_grading=not no_submit,
            )
        finally:
            await client.close()

    _print_json(_run(_submit()))


@app.command()
def unsubmit(
    cmid: int = typer.Argument(..., help="course-module id of the assignment"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Confirm removal"),
) -> None:
    """Remove your submission for an assignment (irreversible)."""
    if not yes:
        typer.secho("Refusing without --yes.", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(1)

    async def _unsubmit():
        client = await connect()
        try:
            return await services.remove_submission(client, cmid)
        finally:
            await client.close()

    _print_json(_run(_unsubmit()))


@app.command()
def page(
    url: str = typer.Argument(..., help="Path or full moodle.umontpellier.fr URL"),
    html: bool = typer.Option(False, "--html", help="Print raw HTML instead of text"),
) -> None:
    """Fetch any Moodle page and print it as text (or raw HTML)."""

    async def _page():
        client = await connect()
        try:
            if html:
                body, final = await client.get_text(url)
                return {"html": body, "url": final}
            return await services.get_page(client, url)
        finally:
            await client.close()

    data = _run(_page())
    if html:
        typer.echo(data["html"])
    elif data.get("binary"):
        typer.echo(f"# {data['url']} ({data['content_type']}, {data['bytes']} bytes)")
        typer.echo(data["hint"])
    else:
        typer.echo(f"# {data['url']}\n")
        typer.echo(data["text"])


@app.command()
def raw(
    url: str = typer.Argument(...),
    out: Path = typer.Option(Path("/tmp/moodle-page.html"), "--out", "-o"),
) -> None:
    """Save a page's raw HTML (for debugging parsers)."""

    async def _raw():
        client = await connect()
        try:
            body, final = await client.get_text(url)
            out.write_text(body)
            return final
        finally:
            await client.close()

    final = _run(_raw())
    typer.echo(f"Saved {final} -> {out}")


@app.command()
def browse(
    url: str = typer.Argument(...),
    actions: str = typer.Option(
        None, "--actions", help='JSON list of actions, e.g. \'[{"type":"click","selector":"text=Next"}]\''
    ),
    screenshot: bool = typer.Option(False, "--screenshot"),
) -> None:
    """Open a page in a headless browser, optionally click/fill, print result."""
    parsed = json.loads(actions) if actions else []
    result = _run(browser.run_actions(url, parsed, screenshot=screenshot))
    _print_json(result)


@app.command()
def download(
    url: str = typer.Argument(..., help="File URL (pluginfile.php/...)"),
    out: Path = typer.Option(None, "--out", "-o", help="Destination path"),
) -> None:
    """Download a course file."""

    async def _download():
        client = await connect()
        try:
            return await client.download(url, out)
        finally:
            await client.close()

    _print_json(_run(_download()))


@app.command()
def keepalive(
    once: bool = typer.Option(False, "--once", help="Ping once and exit"),
    interval: int = typer.Option(
        600, "--interval", "-i", help="Seconds between pings in loop mode"
    ),
) -> None:
    """Ping Moodle periodically to keep the session from expiring."""
    from .keepalive import ping_once, run_forever

    if once:
        _print_json(_run(ping_once()))
        return
    try:
        asyncio.run(run_forever(interval))
    except KeyboardInterrupt:
        raise typer.Exit(130)


@app.command("mcp")
def mcp_command(
    http: bool = typer.Option(False, "--http", help="Serve Streamable HTTP instead of stdio"),
    host: str = typer.Option("127.0.0.1", "--host", help="HTTP bind host"),
    port: int = typer.Option(8765, "--port", help="HTTP bind port"),
    path: str = typer.Option("/mcp", "--path", help="Streamable HTTP endpoint path"),
) -> None:
    """Run the MCP server (stdio by default, or Streamable HTTP)."""
    if http:
        os.environ["MOODLE_UM_MCP_TRANSPORT"] = "http"
        os.environ["MOODLE_UM_MCP_HOST"] = host
        os.environ["MOODLE_UM_MCP_PORT"] = str(port)
        os.environ["MOODLE_UM_MCP_PATH"] = path
    from .mcp_server import main as mcp_main

    mcp_main()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
