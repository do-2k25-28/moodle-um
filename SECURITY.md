# Security policy

## Session data

`moodle-um` authenticates through the university ENT/CAS flow. It **never asks
for or stores your ENT password**. After a successful login it saves the
resulting browser state (cookies, including `MoodleSession` and the CAS
session) under:

```
~/.config/moodle-um/storage_state.json   (mode 0600)
```

Treat this file like a password: anyone who can read it can act as you on
Moodle until the session expires.

- Do not commit `~/.config/moodle-um/`, `keepalive.log`, or browser profiles.
- Do not paste session files or cookies into issues, screenshots, or chats.
- Revoke access by logging out of Moodle/ENT and deleting the directory.
- The optional keepalive timer only sends authenticated requests to
  `moodle.umontpellier.fr`; it does not transmit data anywhere else.

## Reporting a vulnerability

Please open a private security advisory on GitHub rather than a public issue
if the report involves:

- credential or cookie exposure,
- a way to send session data to a non-university host,
- arbitrary code execution through downloaded course content,
- a bypass of the submission confirmation guard.

For ordinary bugs, use the issue tracker.

## Scope and ethics

This project is an independent client for a Moodle instance. It is not
affiliated with or endorsed by Université de Montpellier.

It must not be used to bypass **Safe Exam Browser**, proctoring, lockdown
browsers, or any exam access rule. It deliberately has no SEB bypass. Users are
responsible for following their institution's rules on academic integrity.
