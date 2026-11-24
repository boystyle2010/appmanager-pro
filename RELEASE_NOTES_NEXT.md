# Ghi chú cho bản phát hành kế tiếp — mỗi dòng bắt đầu bằng "- "
- Duplicate compose popup: shows the app icon, name and image at the top; the warning icon now sits next to the warning text.
- App data folder setup: when AppManager cannot read some apps' docker-compose files (data folder not mounted), a popup offers Manual entry or Auto Scan (Docker labels + read-only disk scan in a helper container), then adds the confirmed folders as volumes to AppManager's docker-compose.yml and restarts it with health check and automatic rollback. Also available in Settings → Storage.
- App cards whose compose file cannot be read now explain why (expected path, folder to mount with a ready-to-copy line, or "created with docker run") and open a fix popup.
- Convert to compose: containers created with `docker run` can be converted to a generated, editable docker-compose.yml; named volumes are kept, the old container is only removed after the new one runs correctly and is restored on failure.
- Portainer stacks: compose files in Portainer's data volume are found and run with the stack's real project name and stack.env.
- README: ready-made compose examples for plain Ubuntu/Debian, Dockge, Portainer, docker run containers and Podman (experimental).
- New architecture: linux/arm/v7 (32-bit ARM) images.
