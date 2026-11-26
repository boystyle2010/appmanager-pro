# Ghi chú cho bản phát hành kế tiếp — mỗi dòng bắt đầu bằng "- "
- Fixed: release channels (beta / dev…) could disappear after an update when Docker Hub or the registry briefly refused the channel lookup (e.g. rate limit right after pulling); the last known channels are now kept until a successful check says otherwise.
- Releases are now made only by hand: pushes and the daily run still update components and rebuild the `latest` image, but no longer bump the version or publish a release on their own.
- Automated tests on GitHub Actions for every push and pull request: code checks plus real-Docker scenarios (updates and rollback, docker run, Edit Config, uninstall, rate limits, registry accounts, notifications, API Tokens, multiple servers, release channels).
- Community files: CONTRIBUTING.md, SECURITY.md (private vulnerability reporting), bug / feature issue forms and a pull request template.
