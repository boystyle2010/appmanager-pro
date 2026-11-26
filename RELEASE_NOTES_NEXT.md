# Ghi chú cho bản phát hành kế tiếp — mỗi dòng bắt đầu bằng "- "
- Optional content encryption for notifications: Bark (AES-CBC, only the Bark app on your iPhone can read the message — not api.day.app or a Bark server) and Webhook (AES-256-GCM, still HMAC-signed). Key generator and setup steps in the channel form.
- Optional Private mode for every channel: only a short title is sent (no app names, IP addresses or details).
