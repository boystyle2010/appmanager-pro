"""0.27 ngôn ngữ (không cần Docker): danh sách ngôn ngữ + % đã dịch, tin nhắn thông báo theo ngôn ngữ (kể cả kiểu điện thoại),
chỗ trống {x}, ngôn ngữ lạ bị từ chối, file dịch hỏng không làm sập, công cụ scripts/i18n.py phát hiện lỗi bản dịch, API lưu ngôn ngữ."""
import json, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
R = []
def check(n, cond, d=""):
    R.append(bool(cond)); print(("PASS" if cond else "FAIL"), n, ("" if cond else f":: {str(d)[:400]}"), flush=True)

data = tempfile.mkdtemp(prefix="amp_i18n_")
os.environ["APP_DATA_DIR"] = data
from app.core.database import init_db, set_setting  # noqa: E402
init_db()
from app.core import i18n, notify  # noqa: E402

langs = {x["code"]: x for x in i18n.languages()}
check("7 languages: en, vi, zh, es, de, fr, ja", set(langs) >= {"en", "vi", "zh", "es", "de", "fr", "ja"}, list(langs))
check("Every bundled language is 100% translated, native names, locale", all(x["coverage"] == 100 and x["name"] and x["locale"] for x in langs.values()),
      {k: (v["coverage"], v["name"], v["locale"]) for k, v in langs.items()})
check("Machine-assisted drafts are marked", all(langs[c]["draft"] for c in ("zh", "es", "de", "fr", "ja")) and not langs["vi"]["draft"])

set_setting("notify_lang", "ja")
check("Notification language ja: titles in Japanese", notify.tr("update_success") == "✅ 更新しました", notify.tr("update_success"))
t, b = notify.native("update_success", "x", "y", {"app": "scrypted", "title": "Scrypted", "to": "v0.148.9", "status": "success", "mode": "manual"})
check("Phone-style message in Japanese with the version filled in", t == "Scrypted" and b == "0.148.9 に更新しました", (t, b))
set_setting("notify_lang", "de")
check("Placeholders filled (de security message)", notify.trf("sec_pw_changed", user="anna", ip="10.0.0.5") == "Das Passwort von anna wurde geändert (IP 10.0.0.5).",
      notify.trf("sec_pw_changed", user="anna", ip="10.0.0.5"))
set_setting("notify_lang", "xx")
check("Unknown language falls back to English", notify.tr("update_success") == "✅ Updated")
set_setting("notify_lang", "en")

# file dịch hỏng / thiếu khoá -> dùng tiếng Anh, không sập
tmp = Path(tempfile.mkdtemp())
for f in i18n.I18N_DIR.glob("*.json"):
    shutil.copy(f, tmp / f.name)
(tmp / "it.json").write_text("{ broken", encoding="utf-8")
(tmp / "pt.json").write_text(json.dumps({"_meta": {"name": "Português", "english": "Portuguese", "locale": "pt-PT"}, "notify": {"update_success": "✅ Atualizado"}}), encoding="utf-8")
old = i18n.I18N_DIR
i18n.I18N_DIR = tmp; i18n.pack.cache_clear(); i18n.languages.cache_clear()
codes = {x["code"]: x for x in i18n.languages()}
check("Broken translation file is skipped (no crash)", "it" not in codes and "pt" in codes)
check("Partial translation: coverage below 100 %", codes["pt"]["coverage"] < 100, codes["pt"])
set_setting("notify_lang", "pt")
check("Partial translation: translated text used, the rest in English",
      notify.tr("update_success") == "✅ Atualizado" and notify.tr("update_failed") == "❌ Update failed")
set_setting("notify_lang", "en")
i18n.I18N_DIR = old; i18n.pack.cache_clear(); i18n.languages.cache_clear()

# công cụ người dịch
chk = subprocess.run([sys.executable, str(ROOT / "scripts" / "i18n.py"), "check"], capture_output=True, text=True)
check("scripts/i18n.py check: all bundled files valid, en.json up to date", chk.returncode == 0, chk.stdout + chk.stderr)
sys.path.insert(0, str(ROOT / "scripts"))
import importlib.util  # noqa: E402
spec = importlib.util.spec_from_file_location("i18ntool", ROOT / "scripts" / "i18n.py"); tool = importlib.util.module_from_spec(spec); spec.loader.exec_module(tool)
en = json.loads((i18n.I18N_DIR / "en.json").read_text(encoding="utf-8"))
bad = {"_meta": {"name": "X", "english": "X", "locale": "x"}, "ui": {"svApps": "apps", "nope_key": "?", "weekdays": ["a"]}, "login": {}, "notify": {}}
errs = tool.problems("xx", bad, en)
check("Tool finds a missing {placeholder}, an unknown key and a wrong list",
      any("svApps" in e and "placeholders" in e for e in errs) and any("nope_key" in e for e in errs) and any("weekdays" in e for e in errs), errs)
miss = subprocess.run([sys.executable, str(ROOT / "scripts" / "i18n.py"), "missing", "de"], capture_output=True, text=True)
check("scripts/i18n.py missing de: nothing missing", miss.returncode == 0 and all(not v for v in json.loads(miss.stdout).values()), miss.stdout[:200])

# API: lưu ngôn ngữ tin nhắn + trang có danh sách ngôn ngữ
PORT = 8759; B = f"http://127.0.0.1:{PORT}"; H = {"Origin": B}
env = {**os.environ, "APP_DATA_DIR": tempfile.mkdtemp(prefix="amp_i18n_api_"), "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT)], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(60):
        try:
            if httpx.get(B + "/api/health", timeout=1).status_code == 200: break
        except Exception: pass
        time.sleep(0.5)
    pw = "Test-Passw0rd!x"
    httpx.post(B + "/api/auth/setup", json={"username": "admin", "password": pw, "confirm_password": pw}, headers=H)
    a = httpx.Client(base_url=B, headers=H); a.post("/api/auth/login", json={"username": "admin", "password": pw})
    a.post("/api/notify/settings", json={"lang": "zh"})
    s1 = a.get("/api/notify").json().get("settings", {})
    a.post("/api/notify/settings", json={"lang": "klingon"})
    s2 = a.get("/api/notify").json().get("settings", {})
    check("API: message language zh saved, unknown language ignored", s1.get("lang") == "zh" and s2.get("lang") == "zh", (s1.get("lang"), s2.get("lang")))
    page = a.get("/").text; login = httpx.get(B + "/login").text
    check("Pages embed the language list (index + login)", all('"code": "%s"' % c in page and '"code": "%s"' % c in login for c in ("zh", "ja", "de")) and "AMP_LANGS" in page, page[:200])
    j = httpx.get(B + "/static/i18n/fr.json")
    check("Language file served as JSON", j.status_code == 200 and j.json()["ui"]["settings"] == "Paramètres")
finally:
    proc.terminate()
print(f"SUMMARY {sum(R)} / {len(R)}")
