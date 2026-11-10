# Roadmap

## Now (v0.1)

- ENT/CAS login through a real browser, saved session, keepalive timer.
- Courses, sections, activities, resources, files.
- Assignments: list, detail, submission (files + online text), remove.
- Grades, calendar, generic page reading, generic browser actions.
- CLI and MCP server (stdio), DSH bundle.

## Done (v0.3): quiz read → solve → submit

- `moodle_quiz_start` starts/resumes an attempt and returns questions, choices,
  select options, text fields and input names.
- `moodle_quiz_attempt` reads an in-progress page; finished attempts are parsed
  from the review page with correct-answer markers.
- `moodle_quiz_solve` maps question-number/label answers to Moodle inputs and
  saves the page.
- `moodle_quiz_submit` finishes the attempt, with `confirm=true`.
- Tested with offline fixtures, a mocked save/submit flow, and a real review
  page.

## Next: full end-to-end lab and more question types

- Run the local Moodle Docker lab (see `tests/fixtures/moodle/`) and exercise a
  complete attempt: start → save → next page → submit → review.
- Add explicit support for matching (multiple selects per question), drag-and-
  drop, ordering and cloze, or document the browser fallback clearly.
- Add an answer-sheet/summary step before `moodle_quiz_submit`.
- Detect password-protected and SEB-only quizzes before starting.

## Test lab for quiz support

See [docs/quiz-test-lab.md](docs/quiz-test-lab.md). In short:

1. **Offline fixtures** — save real attempt HTML for each question type and
   unit-test the parser/form builder.
2. **Local Moodle** — Docker Compose with Moodle 4.5 + MariaDB and a fixture
   course backup, so attempts can be started and submitted without touching the
   university instance.
3. **Practice quiz** — one real Moodle quiz with unlimited attempts, used only
   with explicit consent.
4. **Never** test against a graded exam or a proctored/SEB quiz.

## Later

- Forums: list discussions, read posts, reply (with confirmation).
- Messages/notifications.
- Assignment feedback and rubric reading.
- Calendar export (`.ics`).
- Better HTML→text for PDFs/office attachments.
- Localization (French/English UI strings).
