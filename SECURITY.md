# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability, **please do not open a public issue**.
Instead, report it privately by opening a GitHub Security Advisory on the
repository (Settings → Security → Security Advisories → New advisory) or by
emailing the maintainer directly.

Please include:
- A description of the vulnerability
- Steps to reproduce (if possible)
- Impact assessment

The maintainer will acknowledge reports within 7 days and coordinate a fix.

## Safe handling of secrets
- **Never commit API keys, tokens, or credentials.**
- If you believe a secret was committed, treat it as compromised and rotate it.
- Use environment variables or gitignored config files (see `.gitignore`).

## Supported versions
This project is maintained on the `main` branch. Security fixes are applied
there and released as soon as possible.
