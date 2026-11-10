# Local Moodle quiz lab

Disposable Moodle instance for testing quiz-attempt support without touching a
real graded exam.

```bash
docker compose -f tests/fixtures/moodle/docker-compose.yml up -d
# open http://localhost:8080 and finish the Moodle installer
```

Then:

1. Create a course and a **practice quiz** with unlimited attempts.
2. Add one question of each type: multichoice, true/false, short answer,
   numerical, matching, essay, gap-select.
3. Create a test student account.
4. Export the course as a Moodle backup (`.mbz`) and keep it outside git (it may
   contain user data). The lab is intentionally not committed as a binary.

The university instance is **not** used for this test. See
[`docs/quiz-test-lab.md`](../../../docs/quiz-test-lab.md) for the full plan and
acceptance criteria.
