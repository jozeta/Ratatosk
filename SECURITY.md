# Security Policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems.

Report it privately through GitHub instead: go to the **Security** tab of this repository and click
**Report a vulnerability** ([direct link](https://github.com/jozeta/Ratatosk/security/advisories/new)).
Include what you found, how to reproduce it, and the impact you expect.

This is a personal project maintained in spare time. You can expect an acknowledgement within a
week. Fixes are released as soon as practical, and you'll be credited in the advisory unless you
prefer otherwise.

## Scope

In scope: anything that lets the server or a third party read file contents or keys (the zero-knowledge guarantee), authentication or session bypass, access-control flaws, XSS/CSP bypass, and weaknesses in the encryption format documented in `frontend/static/js/crypto.js`. The internal audit is in [`docs/AUDIT.md`](docs/AUDIT.md).

## Supported versions

Only the latest version on the `main` branch receives security fixes.
