# Ghi chú cho bản phát hành kế tiếp — mỗi dòng bắt đầu bằng "- "
- Fixed changelogs failing with "Can't find variable: marked" (marked v18 no longer ships `marked.min.js`); changelogs fall back to plain text if the library is missing, and the build now fails instead of shipping a missing library
- Updates, rollback and compose editing now use the exact compose file the container was started from; previously an app re-deployed from the terminal (e.g. in /DATA/AppData/<app>) could be recreated from an older CasaOS copy and become unhealthy
- Restoring a backup now restarts an app that was stuck restarting
- Update history now shows why an update failed and keeps the full update log (View log), including the failing container's last log lines and healthcheck output captured before rollback
