"""
Tải thư viện giao diện về /app/app/static/vendor lúc BUILD image (GitHub Actions có mạng),
để lúc chạy không còn phụ thuộc CDN. Lỗi tải một file chỉ cảnh báo; HTML tự quay về CDN nếu thiếu file.
"""
import re
import sys
import urllib.request
from pathlib import Path

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "app/static/vendor")
FONTS = OUT / "fonts"
FONTS.mkdir(parents=True, exist_ok=True)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

LIBS = {
    "tailwind.js": "https://cdn.tailwindcss.com/3.4.17",
    "marked.min.js": "https://cdn.jsdelivr.net/npm/marked@15.0.6/marked.min.js",
    "purify.min.js": "https://cdn.jsdelivr.net/npm/dompurify@3.2.3/dist/purify.min.js",
    "alpine.min.js": "https://cdn.jsdelivr.net/npm/alpinejs@3.14.8/dist/cdn.min.js",
}
FONT_CSS = {
    "fonts.css": "https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500"
                 "&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap",
    "fonts-auth.css": "https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap",
}


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read()


def main() -> int:
    failed = 0
    for name, url in LIBS.items():
        try:
            data = get(url)
            if len(data) < 1000:
                raise ValueError("file quá nhỏ")
            (OUT / name).write_bytes(data)
            print(f"ok   {name} ({len(data)//1024} KB)")
        except Exception as exc:
            failed += 1
            (OUT / name).unlink(missing_ok=True)
            print(f"WARN {name}: {exc}")

    for name, url in FONT_CSS.items():
        try:
            css = get(url).decode("utf-8")
            for furl in sorted(set(re.findall(r"url\((https://[^)]+\.woff2)\)", css))):
                fname = re.sub(r"[^A-Za-z0-9._-]", "_", furl.split("fonts.gstatic.com/")[-1])
                fpath = FONTS / fname
                if not fpath.exists():
                    fpath.write_bytes(get(furl))
                css = css.replace(furl, f"/static/vendor/fonts/{fname}")
            (OUT / name).write_text(css, encoding="utf-8")
            print(f"ok   {name}")
        except Exception as exc:
            failed += 1
            (OUT / name).unlink(missing_ok=True)
            print(f"WARN {name}: {exc}")
    return 0  # không làm hỏng build; HTML có CDN dự phòng


if __name__ == "__main__":
    sys.exit(main())
