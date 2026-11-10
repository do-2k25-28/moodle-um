# Roadmap

## Now (v0.1)

- ENT/CAS login through a real browser, saved session, keepalive timer.
- Courses, sections, activities, resources, files.
- Assignments: list, detail, submission (files + online text), remove.
- Grades, calendar, generic page reading, generic browser actions.
- CLI and MCP server (stdio), DSH bundle.

## Next: first-class quiz attempts

The goal is to let the MCP **read an actual quiz attempt, expose the questions
and answer fields to the model, and save/submit answers**. The model proposes
answers; the user confirms before final submission. It is not an autonomous
exam solver, and it will not bypass SEB/proctoring.

### Tool surface

| Tool | Purpose |
| --- | --- |
| `moodle_quiz_start(cmid)` | Start (or resume) an attempt, return attempt id + page |
| `moodle_quiz_get_attempt(attemptid, page=0)` | Questions, choices, input names, timer, navigation |
| `moodle_quiz_save_attempt(attemptid, answers, page=0)` | Save answers / move to next page |
| `moodle_quiz_submit(attemptid, confirm=true)` | Final submit, with summary |
| `moodle_quiz_review(attemptid)` | Read the reviewed attempt after grading |

### Implementation notes

- Start with a POST to `/mod/quiz/startattempt.php` (`cmid`, `sesskey`),
  following the redirect to `/mod/quiz/attempt.php?attempt=…`.
- Parse the response form: hidden `attempt`, `thispage`, `sesskey`; question
  inputs named `q<slot>:<qa>_…`.
- Map common question types to answer payloads: multichoice, true/false,
  shortanswer, numerical, matching, essay, gapselect.
- Save by POSTing the attempt form to `/mod/quiz/processattempt.php` with the
  page navigation fields; final submit uses `finishattempt=1`.
- Preserve the timer and page-access rules; never skip `check_page_access`.
- Detect password-protected quizzes and SEB access rules and stop with a clear
  message.

### Open questions

- Question HTML differs by theme and Moodle version; fixtures are required.
- Some types (drag-and-drop, cloze) need special handling or a browser fallback.
- Essay answers: save text, but expect manual grading.

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
