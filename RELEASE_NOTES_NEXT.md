# Ghi chú cho bản phát hành kế tiếp — mỗi dòng bắt đầu bằng "- "
- Security: pip is removed from the image after installing dependencies (not needed at runtime); its vendored pkg_resources from setuptools 70.3.0 was the remaining Trivy HIGH finding (CVE-2025-47273)
- CI: the verify builds (amd64 + emulated arm64) reuse the GitHub Actions build cache, so unchanged apt / pip layers are no longer rebuilt on every run
- Fixed the Merge / Skip buttons of the duplicate-compose warning being disabled; Merge is now red and the warning uses a vector icon instead of an emoji
- CI: GitHub Actions updated to their latest majors (checkout v7, setup-python v7, setup-node v7, ghaction-github-runtime v4), all on Node.js 24 — no more Node 20 deprecation warning
- CI: the update bot also upgrades GitHub Actions in the workflow to their latest major (skipped when a used input disappears; SHA-pinned actions untouched) when the WORKFLOW_TOKEN secret is set
