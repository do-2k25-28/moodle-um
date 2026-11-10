# Moodle UM — CLI + MCP server

[![CI](https://github.com/do-2k25-28/moodle-um/actions/workflows/ci.yml/badge.svg)](https://github.com/do-2k25-28/moodle-um/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-stdio-6f42c1.svg)](https://modelcontextprotocol.io/)

A CLI and **MCP server** for the University of Montpellier Moodle
(<https://moodle.umontpellier.fr>). It signs in through the real **ENT/CAS**
flow, then lets you or an AI agent browse courses, read and submit assignments,
download course files, check grades and deadlines, and drive pages that have no
dedicated tool.

> Independent project. Not affiliated with or endorsed by Université de
> Montpellier. Use it responsibly — see [Responsible use](#responsible-use).

## First run — sign in once

**The only manual step is the first ENT login.** Do it once before using the
CLI or connecting an MCP client:

```bash
uv run moodle-um login
```

A Chromium window opens on the ENT/CAS page. Sign in with your identifiant and
MFA; the window closes automatically when the Moodle session is detected. The
session is saved in `~/.config/moodle-um/` (mode `0600`) and reused by every CLI
command and MCP tool.

- **No password is stored** — only the resulting session cookies.
- **MCP:** if `moodle_status` returns `authenticated: false`, call
  `moodle_login` once before any other tool. The server does not open a browser
  by itself.
- **Expired session:** run `moodle-um login` again, or keep it alive with the
  [keepalive timer](#keep-the-session-alive).
- You do **not** sign in per command, per course, or per tool call.

## What it can do

| Area | Capabilities |
| --- | --- |
| **Courses** | List enrolled courses, sections, activities, resources, descriptions, completion info |
| **Assignments** | List *devoirs*, due dates, submission status, instructions, attachments |
| **Submission** | Upload files and/or online text, accept the originality statement, final submit, remove a submission |
| **Files** | Download `pluginfile.php` resources, assignment attachments, course documents |
| **Grades** | Read the per-course grade report |
| **Calendar** | Upcoming deadlines and action events |
| **Quizzes** | List quizzes, read settings/attempts/grades, **start or resume an attempt and get structured questions + choices**; finished attempts are parsed from the review page |
| **Any page** | Fetch any Moodle page as Markdown, or drive it with a headless browser (`click`, `fill`, `select`, `check`, `set_file`, `goto`) |
| **Interfaces** | Typer CLI + stdio MCP server (Claude Desktop, Claude Code, Cursor, DeepSeek Harness, any MCP client) |
| **Session** | One interactive ENT login, saved cookies, optional keepalive timer |

## What it cannot do (yet)

| Limitation | Detail |
| --- | --- |
| **No SEB / proctoring bypass** | Safe Exam Browser, lockdown browsers and proctoring are not bypassed. If an exam requires SEB, use SEB. |
| **No answer saving/submission yet** | The quiz reader returns questions and choices; saving answers and final submission are the next milestone — see [ROADMAP.md](ROADMAP.md). |
| **No autonomous exam solving** | There is no "solve this graded exam" tool. The model presents questions and proposed answers; the user decides. |
| **No teacher/admin actions** | The tool acts as the logged-in student. |
| **Not every activity type** | BigBlueButton, H5P, attendance, etc. are reachable through the generic page/browser tools, not first-class tools. |
| **MFA is interactive** | No password is stored, so the first login needs a browser and MFA. |
| **Session lifetime** | Moodle expires idle sessions after ~2 h. The keepalive timer prevents this while the machine is awake; a long suspend can still require a new login. |

## Quick start

Requirements: Python ≥ 3.12, [uv](https://docs.astral.sh/uv/), and Chromium or
Google Chrome.

```bash
git clone https://github.com/do-2k25-28/moodle-um.git
cd moodle-um
uv sync
uv run moodle-um login   # once — see "First run"
uv run moodle-um status
```

`login` opens a Chromium window on the ENT/CAS page. Sign in with your
identifiant and MFA; the window closes automatically and the session is saved in
`~/.config/moodle-um/` (mode `0600`). No password is stored.

> The login window needs a graphical session (`DISPLAY` / Wayland). On a remote
> machine, run it from the desktop session or use X11 forwarding.

Optional — install the commands on your `PATH`:

```bash
uv tool install .
# moodle-um ... / moodle-um-mcp
```

## CLI

```bash
uv run moodle-um courses                  # all enrolled courses
uv run moodle-um courses -q ansible       # filter
uv run moodle-um course <course-id>       # sections + activities
uv run moodle-um assignments <course-id>  # devoirs, due dates, status
uv run moodle-um assignment <cmid>        # one devoir in detail
uv run moodle-um upcoming -n 20           # deadlines / calendar
uv run moodle-um grades <course-id>       # grade report
uv run moodle-um quizzes <course-id>
uv run moodle-um quiz <cmid>
uv run moodle-um quiz-start <cmid>          # start/resume, get questions + choices
uv run moodle-um quiz-attempt <attempt-id>  # read a page of an attempt
```

Read any page as Markdown:

```bash
uv run moodle-um page '/mod/forum/view.php?id=<id>'
uv run moodle-um page '/course/view.php?id=<course-id>'
```

Download a file:

```bash
uv run moodle-um download 'https://moodle.umontpellier.fr/pluginfile.php/...'
# -> ~/Downloads/moodle-um/<filename>
```

### Submit a devoir

```bash
uv run moodle-um submit <cmid> \
  --file ~/Documents/rapport.pdf \
  --text "Quelques remarques…" \
  --yes

# Undo an accidental submission:
uv run moodle-um unsubmit <cmid> --yes
```

- `--file` can be repeated.
- `--no-submit` stops after saving. **Careful:** some assignments do not use
  drafts, so saving is already a final submission. The command reports
  `submitted_for_grading` and adds a warning in that case.
- `--yes` is mandatory: the action may be graded and cannot be undone.
- If the assignment shows an originality statement ("Ce document est le fruit
  de mon propre travail…"), the tool accepts it when submitting.

The MCP equivalent is `moodle_submit_assignment` and also requires
`confirm=true`.

### Drive a page with the headless browser

For quizzes or any JS-heavy page:

```bash
uv run moodle-um browse '/mod/quiz/view.php?id=<cmid>' \
  --actions '[{"type":"click","selector":"a[href*=\"startattempt.php\"]"}]'
```

It returns the page text, URL, and every visible form element (name, label,
options). Use a second call with the returned attempt URL to fill answers and
click **Next page** / **Finish attempt**.

Supported actions: `click`, `fill`, `type`, `select`, `check`, `uncheck`,
`press`, `set_file`, `goto`, `wait`, `wait_for`, `scroll`.

## MCP server

The server uses **stdio**. Point your MCP client at the installed binary, or
run it through `uv`:

```json
{
  "mcpServers": {
    "moodle-um": {
      "command": "/absolute/path/to/moodle-um/.venv/bin/moodle-um-mcp"
    }
  }
}
```

```json
{
  "mcpServers": {
    "moodle-um": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/moodle-um", "run", "moodle-um-mcp"]
    }
  }
}
```

### Claude Desktop

Merge the JSON above into
`~/.config/Claude/claude_desktop_config.json` (Linux) or
`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS), then
restart Claude Desktop.

### Claude Code

```bash
claude mcp add moodle-um -- /absolute/path/to/moodle-um/.venv/bin/moodle-um-mcp
```

### Cursor

Put the same `mcpServers` object in `.cursor/mcp.json` (project) or
`~/.cursor/mcp.json` (global). See [`examples/`](examples/).

### DeepSeek Harness

A config-only bundle is included in [`dsh-bundle/`](dsh-bundle/). Edit its
`cordis.patch.yml` to replace `/path/to/moodle-um`, then:

```bash
# from a terminal:
dsh plugin --profile web add file:$PWD/dsh-bundle

# or from the DSH plugin-manager tool:
plugin_manager install_bundle target=file:$PWD/dsh-bundle
```

Tools appear as `mcp__um__moodle_*` (the server name is `um`). Remove with
`plugin_manager remove_bundle target=@local/dsh-moodle-um`.

### Tools exposed

| Tool | What it does |
| --- | --- |
| `moodle_status` | Check the saved session and who is logged in |
| `moodle_login` | Open the ENT login window (interactive, once) |
| `moodle_list_courses` | Enrolled courses, with ids |
| `moodle_get_course` | Sections, activities, descriptions, file links |
| `moodle_list_assignments` | Devoirs + due dates + submission status |
| `moodle_get_assignment` | Instructions, attachments, status, edit/remove URLs |
| `moodle_submit_assignment` | Upload files / online text; final submit (`confirm=true`) |
| `moodle_remove_submission` | Undo an accidental submission (`confirm=true`) |
| `moodle_list_quizzes` | Quizzes in a course |
| `moodle_get_quiz` | Quiz settings, attempts, `start_url` |
| `moodle_quiz_start` | Start/resume an attempt; return questions, choices, input names |
| `moodle_quiz_attempt` | Read one page of an in-progress or finished attempt |
| `moodle_get_grades` | Grade report for a course |
| `moodle_upcoming` | Upcoming deadlines/calendar |
| `moodle_get_page` | Any Moodle page as Markdown |
| `moodle_browser` | Headless browser + click/fill actions |
| `moodle_download_file` | Download a file to `~/Downloads/moodle-um/` |

Typical agent flow:

1. `moodle_list_courses` → pick a course id.
2. `moodle_get_course` / `moodle_list_assignments` → see what is due.
3. `moodle_get_assignment` → read instructions and attachments.
4. Ask the user to confirm, then `moodle_submit_assignment(confirm=true, …)`.
5. For a quiz: `moodle_get_quiz`, then `moodle_quiz_start` / `moodle_quiz_attempt` to read the questions and choices.

The server instructions tell the model to never submit without explicit user
confirmation and never invent answers for an exam.

## Keep the session alive

Moodle expires an idle session after **2 hours**. A lightweight ping slides the
expiry forward:

```bash
uv run moodle-um keepalive --once
```

A systemd user timer can run it every 10 minutes:

```bash
mkdir -p ~/.config/systemd/user
cp systemd/moodle-um-keepalive.service systemd/moodle-um-keepalive.timer \
  ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now moodle-um-keepalive.timer
```

Check it:

```bash
systemctl --user list-timers --all | grep moodle
journalctl --user -u moodle-um-keepalive.service -n 20
tail -f ~/.config/moodle-um/keepalive.log
```

The units use `%h/moodle-um`; adjust them if you cloned elsewhere. This keeps
the session alive while the machine is running and the timer fires. A suspend
longer than two hours can still expire it — run `moodle-um login` after waking.
Fully unattended re-login would require storing ENT credentials and an MFA
secret, which this tool deliberately does not do.

## How it works

```mermaid
flowchart LR
  A[ENT / CAS<br/>MFA] -->|Playwright, once| B[MoodleSession cookies]
  B -->|httpx| C[moodle.umontpellier.fr]
  C --> D[Moodle AJAX API]
  C --> E[HTML pages / forms]
  C --> F[repository_ajax.php<br/>draft uploads]
  B --> G[headless Chromium<br/>quizzes, JS pages]
  B --> H[keepalive timer]
```

- Login is done once in a real browser; session state is stored in
  `~/.config/moodle-um/storage_state.json`.
- Course/assignment data comes from the same HTML and AJAX endpoints the web
  interface uses, so it reflects what you see.
- File submission uploads to Moodle's draft area, then posts the normal
  submission form (including the originality statement when present).
- The generic browser layer handles JS-heavy pages without pretending every
  Moodle activity has a stable API.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `MOODLE_UM_HOME` | `~/.config/moodle-um` | Session/config directory |
| `MOODLE_UM_DOWNLOADS` | `~/Downloads/moodle-um` | Default download directory |
| `MOODLE_UM_BROWSER` | auto-detected | Chromium/Chrome executable |
| `MOODLE_UM_LOGIN_TIMEOUT` | `300` | Seconds to wait for ENT login |
| `MOODLE_UM_SITE` | `https://moodle.umontpellier.fr` | Moodle base URL |

## Quiz attempts

v0.2 adds a first-class **reader** for quiz attempts:

- `moodle_quiz_start(cmid)` starts or resumes an attempt (it does not submit)
  and returns the attempt id, page, timer, question text, choices, select
  options, text fields and the exact input names. Starting can consume one of
  your allowed attempts, so only use it when you explicitly want to take the
  quiz.
- `moodle_quiz_attempt(attemptid, page=0)` reads an in-progress page; if the
  attempt is finished, it parses the review page and returns the questions with
  their correct-answer markers.
- The same data is available from the CLI with `quiz-start` / `quiz-attempt`.

The reader is tested offline against Moodle-shaped fixtures, a mocked
start-attempt flow, and a real finished attempt review page. The Docker lab in
[docs/quiz-test-lab.md](docs/quiz-test-lab.md) is the place to test answer
saving and final submission next.

Saving answers and final submission are the next milestone: see
[ROADMAP.md](ROADMAP.md). Automatic solving of graded exams is intentionally
not implemented; the model should present questions and proposed answers to the
user, who decides.

## Responsible use

This is a client for **your own** Moodle account. Do not use it to:

- bypass Safe Exam Browser, proctoring, or exam access rules;
- submit work that is not yours;
- access another student's data or impersonate someone else.

Submitting an assignment or an exam is final. The CLI and MCP tools require an
explicit confirmation flag; you remain responsible for what you submit. Check
your institution's rules before using automation for graded work.

## Development

```bash
uv sync
uv run pytest -q
uv run ruff check src tests
```

Layout:

```
src/moodle_um/
  auth.py        # Playwright ENT/CAS login + session persistence
  client.py      # cookie-authenticated httpx client, AJAX, downloads
  services.py    # courses, assignments, quizzes, grades, calendar, submit
  parsers.py     # HTML → text / links
  browser.py     # generic headless-browser actions
  keepalive.py   # periodic session ping
  cli.py         # Typer CLI
  mcp_server.py  # FastMCP server
tests/           # offline unit tests + local Moodle lab
systemd/         # optional keepalive timer
dsh-bundle/      # DeepSeek Harness registration
```

Debug a page's raw HTML:

```bash
uv run moodle-um raw '/mod/assign/view.php?id=<cmid>' -o /tmp/page.html
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

## License

MIT — see [LICENSE](LICENSE).
