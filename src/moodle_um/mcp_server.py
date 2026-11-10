"""MCP server exposing Moodle UM to an AI client (stdio transport)."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import auth, browser, quiz, services
from .client import connect

mcp = FastMCP(
    "moodle-um",
    instructions=(
        "Tools for the University of Montpellier Moodle (moodle.umontpellier.fr). "
        "The user signs in through ENT/CAS once. Call `moodle_status` first; if it "
        "reports authenticated=false, call `moodle_login` once before any other "
        "tool. The session is then reused. After that, start with "
        "`moodle_list_courses`, then `moodle_get_course` to see sections and "
        "activities. Use `moodle_get_page` for any page without a "
        "dedicated tool (forums, resources, etc.). ALWAYS ask the user for explicit "
        "confirmation before `moodle_submit_assignment` with confirm=true: it is "
        "irreversible and may be graded. Use `moodle_quiz_start` and "
        "`moodle_quiz_attempt` to read the real questions and choices, then "
        "present them to the user and let the user decide. Never invent answers "
        "for a graded exam."
    ),
)


async def _with_client(fn):
    client = await connect()
    try:
        return await fn(client)
    finally:
        await client.close()


@mcp.tool()
async def moodle_status() -> dict:
    """Check whether a saved Moodle session is valid, and who is logged in.

    Returns user_id, user_name and site URL. Call this first at the start of a
    session; if authenticated is false, call moodle_login once.
    """
    try:
        client = await connect()
    except auth.AuthError as exc:
        return {"authenticated": False, "error": str(exc)}
    try:
        return {
            "authenticated": True,
            "site": client.site,
            "user_id": client.user_id,
            "user_name": client.user_name,
        }
    finally:
        await client.close()


@mcp.tool()
async def moodle_login() -> dict:
    """Open a Chromium window so the user can sign in through ENT/CAS.

    The window stays open until the user completes the ENT login (identifiant,
    password, MFA). It then closes automatically and the session is saved. Only
    needed once, or when the session has fully expired.
    """
    # Reuse a valid (or silently renewable) session before opening a window.
    if auth.storage_exists():
        try:
            client = await connect()
        except Exception:
            pass
        else:
            info = {
                "user_id": client.user_id,
                "user_name": client.user_name,
                "site_url": client.site,
            }
            await client.close()
            return {"authenticated": True, "already_logged_in": True, **info}

    try:
        info = await auth.interactive_login()
    except auth.AuthError as exc:
        return {"authenticated": False, "error": str(exc)}
    return {"authenticated": True, "already_logged_in": False, **info}


@mcp.tool()
async def moodle_list_courses(query: str | None = None) -> dict:
    """List the courses the user is enrolled in.

    Args:
        query: optional case-insensitive filter on course name or shortname.
    """
    courses = await _with_client(lambda c: services.list_courses(c, query))
    return {"count": len(courses), "courses": courses}


@mcp.tool()
async def moodle_get_course(courseid: int) -> dict:
    """Get a course's sections, activities, descriptions, dates and file links.

    Args:
        courseid: Moodle course id (from moodle_list_courses).
    """
    return await _with_client(lambda c: services.get_course(c, courseid))


@mcp.tool()
async def moodle_list_assignments(courseid: int) -> dict:
    """List the assignments ("devoirs") of a course, with due dates and status.

    Args:
        courseid: Moodle course id.
    """
    assignments = await _with_client(lambda c: services.list_assignments(c, courseid))
    return {"count": len(assignments), "assignments": assignments}


@mcp.tool()
async def moodle_get_assignment(cmid: int) -> dict:
    """Get one assignment: instructions, attachments, due date and submission state.

    Args:
        cmid: course-module id (the `id=` value in /mod/assign/view.php?id=...).
    """
    return await _with_client(lambda c: services.get_assignment(c, cmid))


@mcp.tool()
async def moodle_list_quizzes(courseid: int) -> dict:
    """List the quizzes/tests ("tests") of a course.

    Args:
        courseid: Moodle course id.
    """
    quizzes = await _with_client(lambda c: services.list_quizzes(c, courseid))
    return {"count": len(quizzes), "quizzes": quizzes}


@mcp.tool()
async def moodle_quiz_start(cmid: int) -> dict:
    """Start or resume a quiz attempt and return its questions and choices.

    Creates a real attempt on Moodle (it does not submit it). Starting a quiz
    can consume one of your allowed attempts, so only call this when the user
    explicitly asks to start or take the quiz. The result contains the attempt
    id, page, timer, question text, choices and the exact input names to answer
    with. If Moodle requires a password, an honour statement or Safe Exam
    Browser, the result says so instead of starting.

    Args:
        cmid: course-module id of the quiz.
    """
    return await _with_client(lambda c: quiz.start_quiz(c, cmid))


@mcp.tool()
async def moodle_quiz_attempt(attemptid: int, page: int = 0) -> dict:
    """Read one page of an in-progress quiz attempt.

    Returns the same question/choice structure as moodle_quiz_start, without
    creating or submitting anything.

    Args:
        attemptid: attempt id from moodle_quiz_start or the attempt URL.
        page: zero-based page number (default 0).
    """
    return await _with_client(lambda c: quiz.get_attempt(c, attemptid, page))


@mcp.tool()
async def moodle_get_quiz(cmid: int) -> dict:
    """Get a quiz's settings, attempts and available actions.

    Args:
        cmid: course-module id (the `id=` value in /mod/quiz/view.php?id=...).
    """
    return await _with_client(lambda c: services.get_quiz(c, cmid))


@mcp.tool()
async def moodle_get_grades(courseid: int) -> dict:
    """Get the user's grade report for a course.

    Args:
        courseid: Moodle course id.
    """
    return await _with_client(lambda c: services.get_grades(c, courseid))


@mcp.tool()
async def moodle_upcoming(limit: int = 30) -> dict:
    """List upcoming calendar events and deadlines.

    Args:
        limit: maximum number of events (default 30).
    """
    events = await _with_client(lambda c: services.upcoming(c, limit))
    return {"count": len(events), "events": events}


@mcp.tool()
async def moodle_get_page(url: str) -> dict:
    """Fetch any Moodle page and return it as readable Markdown.

    Use this for forums, resources, pages, sections, or anything without a
    dedicated tool. The URL may be a path like `/mod/forum/view.php?id=123` or a
    full https://moodle.umontpellier.fr URL.

    Args:
        url: path or full URL on moodle.umontpellier.fr.
    """
    return await _with_client(lambda c: services.get_page(c, url))


@mcp.tool()
async def moodle_browser(
    url: str,
    actions: list[dict] | None = None,
    screenshot: bool = False,
) -> dict:
    """Browse any Moodle page in a real headless browser, optionally clicking/filling.

    This is the universal fallback for anything without a dedicated tool:
    taking a quiz, filling a form, uploading a file, reading a forum. Each call
    is stateless but the server-side Moodle state persists.

    Action objects (executed in order):
      {"type":"click","selector":"text=Attempt quiz now"}
      {"type":"fill","selector":"#id_answer","value":"42"}
      {"type":"select","selector":"select[name=x]","value":"1"}
      {"type":"check","selector":"input[value=1]"}
      {"type":"set_file","selector":"input[type=file]","value":"/path/file.pdf"}
      {"type":"press","value":"Enter"}
      {"type":"goto","url":"/mod/quiz/attempt.php?attempt=..."}
      {"type":"wait","value":1000}
      {"type":"wait_for","selector":".que"}
      {"type":"scroll","value":800}

    Returns the page title, URL, readable text, and all visible form elements
    (with names/labels/options) plus optional screenshot path. JavaScript
    confirm/alert dialogs are accepted automatically.

    Args:
        url: page to open (path or full university URL).
        actions: optional list of actions to perform before reading the page.
        screenshot: save a PNG screenshot and return its path.
    """
    return await browser.run_actions(url, actions or [], screenshot=screenshot)


@mcp.tool()
async def moodle_download_file(url: str, dest: str | None = None) -> dict:
    """Download a course file (pluginfile.php / resource) to the local disk.

    Args:
        url: file URL from a course or assignment page.
        dest: optional destination path; defaults to ~/Downloads/moodle-um/.
    """
    return await _with_client(lambda c: c.download(url, dest))


@mcp.tool()
async def moodle_remove_submission(cmid: int, confirm: bool = False) -> dict:
    """Remove your submission for an assignment. IRREVERSIBLE.

    Use this to undo an accidental submission. Requires explicit user
    confirmation (confirm=true).

    Args:
        cmid: course-module id of the assignment.
        confirm: must be true.
    """
    if not confirm:
        return {
            "ok": False,
            "error": "confirm=false: ask the user for explicit confirmation first.",
        }
    return await _with_client(lambda c: services.remove_submission(c, cmid))


@mcp.tool()
async def moodle_submit_assignment(
    cmid: int,
    text: str | None = None,
    files: list[str] | None = None,
    submit_for_grading: bool = True,
    confirm: bool = False,
) -> dict:
    """Submit an assignment (online text and/or files). IRREVERSIBLE once submitted.

    Before calling with confirm=true, show the user exactly what will be
    submitted and get an explicit "yes". If the assignment has an originality
    statement checkbox, this tool accepts it on the user's behalf.

    Args:
        cmid: course-module id of the assignment.
        text: online text to submit (optional).
        files: local file paths to upload (optional).
        submit_for_grading: if true, also post the final "Submit assignment"
            step. If false, stop after saving — but note that assignments
            without drafts submit as soon as they are saved.
        confirm: must be true; safety switch against accidental submissions.
    """
    if not confirm:
        return {
            "ok": False,
            "error": "confirm=false: ask the user for explicit confirmation first.",
        }
    return await _with_client(
        lambda c: services.submit_assignment(
            c,
            cmid=cmid,
            text=text,
            files=files,
            submit_for_grading=submit_for_grading,
        )
    )


def main() -> None:
    import logging

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpcore", "mcp", "playwright", "anyio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    mcp.run()


if __name__ == "__main__":
    main()
