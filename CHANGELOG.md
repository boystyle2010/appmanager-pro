# Changelog

## v0.1.0 (Phase 1 - Foundation)
- Initial release of **AppManager Pro** (multi-arch `amd64` / `arm64`).
- Added secure First-Run Admin setup and Login screen with Argon2id hashing, Signed HttpOnly Cookies, and IP brute-force protection (`CF-Connecting-IP` / `X-Forwarded-For` aware).
- Built Liquid Glass UI with Dark/Light modes, EN/VN language switch, and mobile responsiveness.
- Added instant container discovery with automatic CasaOS `x-casaos` metadata extraction (icon, title, WebUI port) and standalone Docker fallback.
- Added Start, Stop, Restart actions and real-time WebSocket Live Logs viewer.
