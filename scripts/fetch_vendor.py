"""
Tải thư viện giao diện về /app/app/static/vendor lúc BUILD image (GitHub Actions có mạng),
để lúc chạy không còn phụ thuộc CDN.
- Thư viện JS (marked, DOMPurify, Alpine) là BẮT BUỘC: tải hỏng -> build hỏng, để bot nâng phiên bản
  phát hiện ngay (vd marked v18 bỏ file marked.min.js) và lùi về bản cũ thay vì phát hành giao diện lỗi.
- Font chỉ cảnh báo; HTML tự dùng font hệ thống nếu thiếu.
"""
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "app/static/vendor")
FONTS = OUT / "fonts"
FONTS.mkdir(parents=True, exist_ok=True)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

LIBS = {
    "marked.min.js": "https://cdn.jsdelivr.net/npm/marked@18.3.0/lib/marked.umd.js",
    "purify.min.js": "https://cdn.jsdelivr.net/npm/dompurify@3.5.0/dist/purify.min.js",
    "alpine.min.js": "https://cdn.jsdelivr.net/npm/alpinejs@3.17.5/dist/cdn.min.js",
}
FONT_CSS = {
    "fonts.css": "https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500"
                 "&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap",
    "fonts-auth.css": "https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap",
}


def get(url: str, attempts: int = 3) -> bytes:
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404 or i == attempts - 1:  # file không tồn tại -> thử lại vô ích
                raise
        except Exception:
            if i == attempts - 1:
                raise
        time.sleep(3 * (i + 1))
    raise RuntimeError("unreachable")


EXPECT = {  # chuỗi phải có trong file thì mới coi là hợp lệ (tránh lưu nhầm trang lỗi HTML)
    "marked.min.js": b"markedjs",
    "purify.min.js": b"DOMPurify",
    "alpine.min.js": b"Alpine",
}
FALLBACK_URLS: dict[str, str] = {}  # Tailwind v4 được biên dịch riêng trong Dockerfile


def valid_js(name: str, data: bytes) -> bool:
    head = data[:200].lstrip().lower()
    return len(data) > 5000 and not head.startswith(b"<") and EXPECT[name] in data


def main() -> int:
    failed = 0
    for name, url in LIBS.items():
        ok = False
        for u in [url, FALLBACK_URLS.get(name)]:
            if not u:
                continue
            try:
                data = get(u)
                if not valid_js(name, data):
                    raise ValueError("nội dung không hợp lệ (không phải JavaScript mong đợi)")
                (OUT / name).write_bytes(data)
                print(f"ok   {name} <- {u} ({len(data)//1024} KB)")
                ok = True
                break
            except Exception as exc:
                print(f"WARN {name} <- {u}: {exc}")
        if not ok:
            failed += 1
            (OUT / name).unlink(missing_ok=True)
            print(f"ERROR {name}: không tải được thư viện bắt buộc", file=sys.stderr)

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
            (OUT / name).unlink(missing_ok=True)
            print(f"WARN {name}: {exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
