# Ghi chú cho bản phát hành kế tiếp — mỗi dòng bắt đầu bằng "- "
- API Docs now open inside AppManager (Settings → API Tokens → API Docs) instead of a new browser tab.
- Wording: "Token", "Script" and "API Docs" are now capitalized in the interface.
- Multiple servers (Settings → Servers): manage the AppManager of other machines from this one. This AppManager calls the other one's REST API over HTTP or HTTPS with an API Token (Bearer) — no Docker socket on the network, no extra agent; requirements and security advice are explained in the app. Requires AppManager 0.17.0 or newer on the other machine.
- A server switcher above the app list (update counts, offline indicator). For another server: list apps, check for updates, update one app or all apps (live log, health check and rollback done by that server), start / stop / restart.
- Connection test before saving (version, app count, Token permission, latency) with clear messages for a wrong or deleted Token, read-only Token, unreachable address, self-signed HTTPS certificate (optional certificate check), AppManager older than 0.17.0 and redirects (never followed). Tokens of other servers are stored only on this machine and never sent to the browser.
- API health (`GET /api/health` with a Token) now also reports the Token permission.
