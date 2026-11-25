# Ghi chú cho bản phát hành kế tiếp — mỗi dòng bắt đầu bằng "- "
- Notifications (Settings → Notify): Telegram, Discord, ntfy, Gotify and Webhook (JSON with optional HMAC signature), with events chosen per channel: updates available (grouped, each version once), update finished, update failed / rolled back, AppManager self-update, app problem (keeps restarting, unhealthy, exits with an error — and recovery), disk almost full, security (IP locked, password changed, 2FA disabled).
- "Send test" per channel with the delivery result; secrets are never shown again after saving.
- Quiet hours: regular messages are held and sent as one summary afterwards; important ones are always sent. Messages in English or Vietnamese.
- Notifications are sent in the background with retries, so an unreachable channel never slows down updates.
