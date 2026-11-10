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

## Remote MCP mode

`moodle-um mcp --http ...` exposes the MCP server over Streamable HTTP. When
published through Tailscale Funnel or another HTTPS reverse proxy, **the URL
path is the only access control**. Treat the full URL as a bearer credential:

- use a random 32-byte path and HTTPS;
- do not paste the URL into screenshots, issues, or logs;
- rotate the path (edit `MOODLE_UM_MCP_PATH`, restart the service) if it leaks;
- the server binds to `127.0.0.1`; do not expose the raw port directly;
- no OAuth is implemented yet, so there is no per-user authorization.

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
