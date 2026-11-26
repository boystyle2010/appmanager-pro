# Contributing to AppManager Pro

Thanks for helping! Bug reports, ideas, translations and pull requests are all welcome.

## Reporting a bug or asking for a feature
- Search the [issues](../../issues) first — someone may have reported it already.
- Use the **Bug report** or **Feature request** form; the questions there (version, how AppManager runs, logs) save a lot of back-and-forth.
- **Security problems:** please do **not** open a public issue — see [SECURITY.md](SECURITY.md).

## Development setup
```bash
git clone https://github.com/boystyle2010/appmanager-pro.git && cd appmanager-pro
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt jinja2 pyflakes
APP_DATA_DIR=./data uvicorn app.main:app --reload --port 8000   # needs access to a Docker daemon
```
The UI uses Tailwind CSS v4, compiled when the image is built. For local screenshots build it once:
`npx @tailwindcss/cli -i app/static/css/tailwind.input.css -o app/static/css/tailwind.css` (the output is not committed).

## Project layout (short)
- `app/main.py` — FastAPI routes · `app/core/` — logic (Docker, registries, updates, rollback, notifications, API tokens, servers…)
- `app/templates/index.html` + `app/static/js/app.js` — Alpine.js UI · `app/static/js/i18n.js` — **every text key exists in English and Vietnamese**
- `tests/docker/` — real-Docker scenario tests (see its README)

## Before opening a pull request
```bash
python -m compileall -q app scripts
python -m pyflakes app scripts tests
python scripts/check_project.py
node --check app/static/js/app.js && node --check app/static/js/i18n.js
S=/tmp/amp-tests bash tests/docker/ci_setup.sh && S=/tmp/amp-tests bash tests/docker/run_ci.sh   # needs Docker, ~30-60 min
```
GitHub Actions runs the same checks and Docker scenarios on every pull request.

## Guidelines
- **Mobile first** — most users open AppManager on a phone; check the UI at 390 px wide.
- **Icons are SVG only** — no emoji in the interface.
- **Every outgoing HTTP request** goes through `app/core/net.py` (`net.client()`): it caches and respects rate limits.
- **Every state-changing API** (`POST/PUT/PATCH/DELETE /api/*`) is protected by the Origin check and writes an audit log entry for important actions.
- **Dangerous actions** show a "What will happen" list and a confirmation.
- Do **not** edit versions in `Dockerfile`, `requirements.txt`, `scripts/fetch_vendor.py`, `APP_VERSION` or `CHANGELOG.md` — the release bot manages them.
- Describe user-visible changes in English, one line each, in `RELEASE_NOTES_NEXT.md`; they go into the changelog of the next release.
- Add or update a scenario in `tests/docker/` for behaviour changes (updates, rollback, notifications, API).

## Translations
Add a new language block to `app/static/js/i18n.js` with the same keys as `en`. Untranslated keys fall back to English. Open a pull request even if only part of it is done.

## License
By contributing you agree that your contributions are licensed under the [MIT License](LICENSE).
