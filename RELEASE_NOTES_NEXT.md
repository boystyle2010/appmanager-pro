# Ghi chú cho bản phát hành kế tiếp — mỗi dòng bắt đầu bằng "- "
- Duplicate compose popup: shows the app icon, name and image at the top; the warning icon now sits next to the warning text.
- App data folder setup: when AppManager cannot read some apps' docker-compose files (data folder not mounted), a popup offers Manual entry or Auto Scan (Docker labels + read-only disk scan in a helper container), then adds the confirmed folders as volumes to AppManager's docker-compose.yml and restarts it with health check and automatic rollback. Also available in Settings → Storage.
