# Roadmap

## Now (v0.1)

- ENT/CAS login through a real browser, saved session, keepalive timer.
- Courses, sections, activities, resources, files.
- Assignments: list, detail, submission (files + online text), remove.
- Grades, calendar, generic page reading, generic browser actions.
- CLI and MCP server (stdio), DSH bundle.

## Done (v0.2): quiz attempt reader

- `moodle_quiz_start(cmid)` starts/resumes an attempt and returns questions,
  choices, select options, text fields and input names.
- `moodle_quiz_attempt(attemptid, page=0)` reads an in-progress page; finished
  attempts are parsed from the review page with correct-answer markers.
- Tested with offline fixtures, a mocked start-attempt flow, and a real review
  page.

## Next: answer saving and final submission

### Tool surface

| Tool | Purpose |
| --- | --- |
| `moodle_quiz_save_attempt(attemptid, answers, page=0)` | Save answers / move to next page |
| `moodle_quiz_submit(attemptid, confirm=true)` | Final submit, with summary |
| `moodle_quiz_review(attemptid)` | Read the reviewed attempt after grading |

### Implementation notes

- Save by POSTing the attempt form to `/mod/quiz/processattempt.php` with the
  hidden `attempt`, `thispage`, `sesskey`, `nextpage` fields and answer inputs.
- Preserve page-access rules and the timer; never skip `check_page_access`.
- Support multiple-choice, true/false, short answer, numerical, matching,
  essay and gap-select first.
- Detect password-protected and SEB quizzes; stop with a clear message.
- Final submit requires `confirm=true` and a user-facing summary.

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
