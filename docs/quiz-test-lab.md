# Quiz support: test lab

## Current coverage (v0.2)

Implemented and tested:

- start/resume an attempt (`moodle_quiz_start`);
- read an in-progress page (`moodle_quiz_attempt`);
- parse a finished attempt review page into questions + choices;
- offline fixtures for multichoice, true/false, short answer, matching, essay
  and gap-select;
- mocked HTTP start-attempt flow (`tests/test_quiz.py`).

Not yet tested end-to-end: saving answers and final submission. Those are the
next milestone and require the local Moodle lab below.

The quiz-attempt feature must be testable **without touching a real graded
exam**. This document describes the test layers, from cheapest to most
realistic.

## 1. Offline HTML fixtures (unit tests)

Save the HTML of a quiz attempt page for each question type under
`tests/fixtures/quiz/`:

```
multichoice.html
truefalse.html
shortanswer.html
numerical.html
matching.html
essay.html
gapselect.html
```

Tests should assert that the parser returns:

- `attemptid`, `page`, `slots`, `timeleft`;
- for each question: `slot`, `type`, `text`, input names, choices;
- a `data` payload that can be posted back unchanged for a known answer.

This catches selector drift when Moodle is upgraded and needs no network.

## 2. Local Moodle instance (integration tests)

Use Docker Compose with a disposable Moodle:

```yaml
services:
  db:
    image: mariadb:10.11
    environment:
      MARIADB_ROOT_PASSWORD: moodle
      MARIADB_DATABASE: moodle
      MARIADB_USER: moodle
      MARIADB_PASSWORD: moodle
  moodle:
    image: moodlehq/moodle-php-apache:4.5
    ports: ["8080:80"]
    environment:
      MOODLE_DATABASE_HOST: db
      MOODLE_DATABASE_NAME: moodle
      MOODLE_DATABASE_USER: moodle
      MOODLE_DATABASE_PASSWORD: moodle
    depends_on: [db]
```

Then:

1. Install Moodle at `http://localhost:8080`.
2. Restore a fixture course backup (`tests/fixtures/moodle/quiz-lab.mbz`)
   containing a **practice quiz** with one question of each type, unlimited
   attempts, no password, no SEB.
3. Create a test student (`student` / `Student123!`).
4. Point the client at the local instance:

   ```bash
   MOODLE_UM_SITE=http://localhost:8080 \
   MOODLE_UM_HOME=/tmp/moodle-um-test \
   uv run moodle-um login   # manual login, or a test-only auth helper
   ```

5. Run the end-to-end test: start attempt → read questions → save answers →
   next page → submit → review → assert score.

Local Moodle uses normal username/password auth, not ENT/CAS, so add a
**test-only** login path (for example `moodle-um login --password`) that is
never used against the university instance. Do not commit test credentials.

## 3. Real practice quiz (manual)

Only if a course has a quiz with **unlimited attempts** and no grading impact:

1. Ask the user for permission.
2. Start one attempt.
3. Verify question parsing, save one page, navigate back, submit.
4. Check the review page and confirm the score is as expected.
5. Do not run this against a quiz that counts toward a grade.

## 4. What to verify

| Case | Expected |
| --- | --- |
| Start attempt | Redirect to `attempt.php`, attempt id captured |
| Timer | `timeleft` shown and not bypassed |
| Multichoice / truefalse | Selected value survives navigation |
| Shortanswer / numerical | Text/number value saved |
| Matching | Pair values saved |
| Essay | Text saved, manual grading expected |
| Page navigation | Previous/next does not lose answers |
| Final submit | Confirmation required, summary shown |
| Password quiz | Clear "password required" message, no attempt started |
| SEB quiz | Refuses with "SEB required", no bypass |
| Attempt limit reached | Clear message, no new attempt |

## 5. Guardrails

- `moodle_quiz_submit` requires `confirm=true`.
- The model must show the questions and proposed answers to the user first.
- No automatic answering of graded exams; the tool is for practice,
  accessibility, and self-assessment.
- No SEB/proctoring bypass. If Moodle says SEB is required, stop.
