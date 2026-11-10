# Changelog

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
