# Ghi chú cho bản phát hành kế tiếp — mỗi dòng bắt đầu bằng "- "
- Uninstalling one service of a multi-service stack now removes only that service (the rest of the stack and its folders are kept)
- Changelogs keep notes that contain commit links; only real checksum lines are hidden
- Trusted proxies default to localhost only; add your proxy's IP in `TRUSTED_PROXIES`
- One failing app no longer stops "Update All" or the nightly auto-update
- Self-update uses AppManager Pro's own image (no more outdated helper image)
- Safer "Open" links, clearer "check already running" message, AppManager Pro can no longer be stopped from its own menu
- CI now boots the real app with uvicorn and builds the arm64 image before publishing; Trivy results list the affected packages
