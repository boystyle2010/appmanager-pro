# Ghi chú cho bản phát hành kế tiếp — mỗi dòng bắt đầu bằng "- "
- Fixed: release channels (beta / dev…) could disappear after an update when Docker Hub or the registry briefly refused the channel lookup (e.g. rate limit right after pulling); the last known channels are now kept until a successful check says otherwise.
