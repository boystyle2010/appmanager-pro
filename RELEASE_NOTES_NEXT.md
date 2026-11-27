# Ghi chú cho bản phát hành kế tiếp — mỗi dòng bắt đầu bằng "- "
- Home Screen app (PWA) on iPhone: the header now leaves more room below the status bar / Dynamic Island.
- Phone-style notifications for Web Push and Bark: no emoji or bullets, short titles like native apps ("Update available", "3 updates available", "Nextcloud updated", "Couldn't update Nextcloud"), up to 4 apps listed then "+N more"; Bark shows the AppManager icon.
- Web Push: tapping an "update available" notification opens the Updates list; the Home Screen app icon shows the number of apps with updates (like the App Store) and clears when there are none; Android shows a small monochrome status-bar icon.
- Fixed: after a rebuilt `latest` image of AppManager Pro, the update could be shown as an older release (e.g. "v0.25.0 → v0.24.0"). An older release name is never shown as the new version, and AppManager images now carry their real version label.
