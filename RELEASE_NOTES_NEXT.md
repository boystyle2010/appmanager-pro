# Ghi chú cho bản phát hành kế tiếp — mỗi dòng bắt đầu bằng "- "
- Uninstall dialog uses red toggle switches (same style as Storage cleanup) instead of checkboxes.
- Rate limits: every outgoing request goes through one layer that caches answers (blobs and release notes of a tag permanently, tag lists for an hour, GitHub revalidated with ETag so unchanged answers do not count), pauses only the limited source until Retry-After / X-RateLimit-Reset (remembered across restarts) and limits parallel requests per source.
- While a source is limited, apps keep their last known update status; cards show "Checks paused until HH:MM (API limit)".
- New Settings section "Update sources & API limits": requests and cache hits per source in the last hour, remaining quota, pauses with "Resume now", and "Clear cached answers".
- Registry accounts (Docker Hub, GHCR, any registry incl. basic-auth registries): tested before saving, used for update checks (raises Docker Hub limits) and for pulling private images, including in the self-update helper; the host's docker config is not modified.
