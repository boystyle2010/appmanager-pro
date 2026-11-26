# Security Policy

AppManager Pro has root-equivalent control of the Docker host (through `/var/run/docker.sock`), so security reports are taken seriously.

## Supported versions
Only the **latest release** receives fixes. Please update before reporting.

## Reporting a vulnerability
- Use GitHub's **private vulnerability reporting**: *Security* tab → **Report a vulnerability**.
- Please do **not** open a public issue or discussion for security problems.
- Include the version, how AppManager runs (CasaOS / Docker Compose / docker run, reverse proxy or not) and steps to reproduce.

You can expect a first answer within a few days. Once a fix is released the report is credited in the release notes (unless you prefer otherwise).

## Hardening tips
- Keep AppManager on your LAN or behind a VPN / authenticated tunnel; do not expose it directly to the Internet.
- Use HTTPS when you access it remotely, turn on two-factor authentication, and give API Tokens the lowest permission and an IP allow-list.
