# Changelog

## 0.4.0 — 2026-11-10

- **Remote MCP mode:** Streamable HTTP transport (`moodle-um mcp --http`),
  suitable for claude.ai custom connectors behind HTTPS.
- `systemd/moodle-um-mcp-http.service` unit and Tailscale Funnel instructions.
- `MOODLE_UM_MCP_TRANSPORT`, `MOODLE_UM_MCP_HOST`, `MOODLE_UM_MCP_PORT`,
  `MOODLE_UM_MCP_PATH` settings.

## 0.3.0 — 2026-11-10

- **Quiz solve/submit:** `moodle_quiz_solve` maps answers by question number,
  choice label/value or raw input name, saves a page; `moodle_quiz_submit`
  finishes with explicit confirmation.
- CLI `quiz-solve` / `quiz-submit`.
- Save/submit tested against Moodle-shaped forms and a mocked
  `processattempt.php`; 17 offline tests.
- README documents the read → solve → submit workflow and limits.

## 0.2.0 — 2026-11-10

- **Quiz attempt reader:** start/resume an attempt and return structured
  questions, choices, select options, text fields and input names.
- Parse finished attempt review pages, including correct-answer markers.
- MCP tools `moodle_quiz_start` / `moodle_quiz_attempt`; CLI `quiz-start` /
  `quiz-attempt`.
- Offline quiz fixtures and a mocked start-attempt integration test.
- README now puts the one-time ENT sign-in at the top.

## 0.1.0 — 2026-11-10

Initial public release.

- ENT/CAS login through Playwright, saved session, silent renewal attempt.
- Courses, sections, activities, resources and file downloads.
- Assignments: list, detail, file/online-text submission, removal.
- Grades, calendar/upcoming, generic page reading.
- Generic headless-browser action tool (`click`, `fill`, `select`, `check`,
  `set_file`, `goto`, …).
- CLI and stdio MCP server.
- Session keepalive command + systemd timer.
- DeepSeek Harness bundle.
- Offline unit tests and CI.
