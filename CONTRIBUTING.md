# Contributing

Thanks for helping. This project is a thin, well-behaved client for Moodle:
prefer using the same web endpoints the browser uses over brittle shortcuts.

## Development setup

```bash
git clone https://github.com/do-2k25-28/moodle-um.git
cd moodle-um
uv sync
uv run moodle-um login   # against the real Moodle, one time
```

Requirements: Python ≥ 3.12, [uv](https://docs.astral.sh/uv/), Chromium or
Google Chrome.

## Checks

```bash
uv run ruff check src tests
uv run pytest -q
```

Please keep unit tests offline. Parser tests should use small HTML fixtures,
not a live Moodle session.

## Adding a feature

1. Prefer a dedicated service in `src/moodle_um/services.py` if Moodle exposes
   a stable page or AJAX endpoint.
2. Otherwise use the generic browser action layer (`browser.py`) and document
   the selectors.
3. Add an MCP tool in `mcp_server.py` with a clear docstring and a confirmation
   flag for anything irreversible.
4. Add a CLI command only when it is useful outside an AI client.
5. Update `README.md` and `ROADMAP.md` if the capability or limitations change.

## Things we do not accept

- Storing ENT passwords, MFA seeds, or session cookies in the repository.
- Bypassing Safe Exam Browser, proctoring, or exam access rules.
- Automatically submitting a graded assignment/exam without an explicit
  confirmation flag and a user-facing warning.
- Scraping other students' data or impersonating another account.

## Commit style

Short imperative subject, e.g. `add quiz attempt metadata`, `fix assignment
status parsing`. Keep machine-specific paths out of committed files.
