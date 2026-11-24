# Ghi chú cho bản phát hành kế tiếp — mỗi dòng bắt đầu bằng "- "
- Release channels: channels without an image for the server's CPU architecture are hidden (e.g. beszel:dev is amd64-only); a pre-release channel without a version number shows its build date and its changelog lists the commits on the main branch since the last stable release instead of the stable release notes
- Images are also published to Docker Hub (boystyle2010/appmanager-pro) with the same tags; the Docker Hub page description is synced from the README
- Copyright line (© boystyle2010 · version · MIT License · GitHub) at the bottom of the dashboard and on the sign-in page; README rewritten for the new features
