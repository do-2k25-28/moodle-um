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
- `browser_profile/` is a Chromium profile (cookies, cache, history) and is
  mode `0700`. `keepalive.log` only contains timestamps and the Moodle user id
  and is mode `0600`.
- Revoke access by logging out of Moodle/ENT and deleting the directory.
- The optional keepalive timer only sends authenticated requests to
  `moodle.umontpellier.fr`; it does not transmit data anywhere else.

## Remote MCP mode (multi-user)

`moodle-um mcp --http ...` exposes one MCP server with **one Moodle session per
person**. Users onboard through `https://<host>/<secret>/connect`:

1. they sign in on their own machine with `moodle-um login`;
2. they upload their `storage_state.json`;
3. the server validates it against Moodle and gives them a personal bearer
   token.

Tokens are stored only as SHA-256 hashes; session directories are under
`~/.config/moodle-um/users/<hash>/` with mode `0600`. The MCP endpoint requires
`Authorization: Bearer <token>` (or `X-Moodle-Token`) and routes the request to
that user's session.

- Treat every token as a password for that user's Moodle account.
- The onboarding URL's random path is also a secret; share it only with people
  who should be able to link an account.
- If a token leaks, the user uploads a fresh session to get a new token; old
  tokens can be revoked by deleting the corresponding user directory.
- No ENT password or MFA secret is stored; only Moodle session cookies.
- HTTPS is required (`tailscale funnel` or a reverse proxy with a real
  certificate).

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
