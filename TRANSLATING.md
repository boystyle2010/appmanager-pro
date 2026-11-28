# Translating AppManager Pro

AppManager Pro is available in **English, Tiếng Việt, 简体中文, Español, Deutsch, Français and 日本語**.
English and Vietnamese are written by the maintainers. The other languages started as a **machine-assisted first draft**:
they are complete, but a native speaker will certainly find wording to improve. Every correction is welcome — even a single word.

Text that is not translated yet is shown in English, so a partial translation is fine.

## Where the texts are

| File | What |
|---|---|
| `app/static/i18n/<code>.json` | One file per language (`de.json`, `fr.json`, …). **This is the file you edit.** |
| `app/static/i18n/en.json` | The English source, generated — use it to see every text. Do not edit. |
| `app/static/js/i18n.js`, `app/templates/auth.html`, `app/core/notify.py` | English + Vietnamese originals (maintainers). |

A language file has four parts:

```json
{
 "_meta": { "name": "Deutsch", "english": "German", "locale": "de-DE", "translators": ["your name"] },
 "ui":     { "settings": "Einstellungen", "svApps": "{n} Apps", ... },
 "login":  { "signIn": "Anmelden", ... },
 "notify": { "update_success": "✅ Aktualisiert", ... }
}
```

- `ui` — the app itself, `login` — the sign-in page, `notify` — notification messages (Telegram, ntfy, Web Push…).
- `locale` sets the date / time format.
- Remove `"machine_draft": true` from `_meta` once a native speaker has reviewed the file.

## Rules

1. **Keep every `{placeholder}` exactly as it is** — `{n}`, `{app}`, `{v}`… are replaced by numbers and names. You may move them inside the sentence.
2. Keep product and technical names as they are: AppManager, Docker, docker-compose.yml, CasaOS, Trivy, Token, API Docs, SSO, HTTPS…
3. Keep the emoji at the start of notification titles (`✅`, `❌`, `🆕`…) — the rest of the interface uses no emoji.
4. Short is better: most texts are buttons or labels on a phone screen.
5. `weekdays` is a list of 7 names, Monday first.

## Improve a translation (easiest)

1. Open the file on GitHub, e.g. [`app/static/i18n/de.json`](app/static/i18n/de.json), and click the pencil icon.
2. Change the texts, then **Propose changes** → **Create pull request**.

No setup is needed. Not comfortable with GitHub? Open an issue with the *Translation* template and paste the corrections.

## Add a new language

1. Copy `app/static/i18n/en.json` to `app/static/i18n/<code>.json` (`it.json`, `pt-BR.json`, `ko.json`…; the code is a 2–3 letter language code, optionally with a region).
2. Fill `_meta` (`name` in your language, `english`, `locale`) and translate as much as you like — delete the lines you do not translate yet.
3. Open a pull request. The new language appears automatically in **Settings → Language** and on the sign-in page, with the percentage translated.

## Check your file (optional)

With Python 3 and Node.js installed:

```bash
python scripts/i18n.py check        # JSON valid, placeholders kept, no unknown keys
python scripts/i18n.py status       # percentage translated per language
python scripts/i18n.py missing de   # English texts still missing in de.json
```

The same check runs automatically on every pull request.

## For maintainers

- A new or changed English text goes into `app/static/js/i18n.js` (or `auth.html` / `notify.py` `T`) **in English and Vietnamese**, then run `python scripts/i18n.py export` to refresh `en.json` (CI fails if it is out of date).
- When an English text changes meaning, update or remove that key in the other language files (`python scripts/i18n.py missing <code>` lists what is missing after removal).
