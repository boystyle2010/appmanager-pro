# Third-party notices

AppManager Pro — Copyright (c) 2026 boystyle2010 — is released under the [MIT License](LICENSE).
The application icon (`assets/icon.png`) is original work by the author and is covered by the same license.

AppManager Pro uses and redistributes the open-source components below. Each remains the property of its
authors and is used under its own license. Full license texts are in [`licenses/`](licenses/) and are copied
into the Docker image at `/app/licenses/`. Version numbers change with each release; see `requirements.txt`,
`Dockerfile` and `scripts/fetch_vendor.py`.

## Bundled in the web interface

| Component | License | Copyright | License text |
|---|---|---|---|
| [Alpine.js](https://github.com/alpinejs/alpine) | MIT | Caleb Porzio and contributors | [alpinejs.LICENSE.txt](licenses/alpinejs.LICENSE.txt) |
| [Tailwind CSS](https://github.com/tailwindlabs/tailwindcss) (compiled stylesheet) | MIT | Tailwind Labs, Inc. | [tailwindcss.LICENSE.txt](licenses/tailwindcss.LICENSE.txt) |
| [marked](https://github.com/markedjs/marked) | MIT | Christopher Jeffrey; MarkedJS | [marked.LICENSE.txt](licenses/marked.LICENSE.txt) |
| [DOMPurify](https://github.com/cure53/DOMPurify) | Apache-2.0 (dual-licensed MPL-2.0 OR Apache-2.0; used under Apache-2.0) | Cure53 and other contributors | [dompurify.LICENSE.txt](licenses/dompurify.LICENSE.txt) |
| [Plus Jakarta Sans](https://github.com/tokotype/PlusJakartaSans) (font) | SIL Open Font License 1.1 | The Plus Jakarta Sans Project Authors | [PlusJakartaSans.OFL.txt](licenses/PlusJakartaSans.OFL.txt) |
| [JetBrains Mono](https://github.com/JetBrains/JetBrainsMono) (font) | SIL Open Font License 1.1 | The JetBrains Mono Project Authors | [JetBrainsMono.OFL.txt](licenses/JetBrainsMono.OFL.txt) |

## Bundled in the Docker image

| Component | License | Copyright | License text |
|---|---|---|---|
| [Docker CLI](https://github.com/docker/cli) | Apache-2.0 | Docker, Inc. | [docker-cli.LICENSE.txt](licenses/docker-cli.LICENSE.txt), [NOTICE](licenses/docker-cli.NOTICE.txt) |
| [Docker Compose](https://github.com/docker/compose) | Apache-2.0 | Docker, Inc. | [docker-compose.LICENSE.txt](licenses/docker-compose.LICENSE.txt), [NOTICE](licenses/docker-compose.NOTICE.txt) |
| [Python](https://www.python.org/) (official `python:*-slim` image) | PSF License | Python Software Foundation | `/usr/local/lib/python3.*/LICENSE.txt` in the image |
| Debian base system packages | Various free licenses | Respective authors | `/usr/share/doc/*/copyright` in the image |

## Python packages (`requirements.txt`)

Installed with their own license files (`/usr/local/lib/python3.*/site-packages/*.dist-info/`).

| Package | License |
|---|---|
| [FastAPI](https://github.com/fastapi/fastapi) | MIT |
| [Starlette](https://github.com/encode/starlette) | BSD-3-Clause |
| [Pydantic](https://github.com/pydantic/pydantic) | MIT |
| [Uvicorn](https://github.com/encode/uvicorn) | BSD-3-Clause |
| [Docker SDK for Python](https://github.com/docker/docker-py) | Apache-2.0 |
| [ruamel.yaml](https://sourceforge.net/projects/ruamel-yaml/) | MIT |
| [argon2-cffi](https://github.com/hynek/argon2-cffi) | MIT |
| [itsdangerous](https://github.com/pallets/itsdangerous) | BSD-3-Clause |
| [Jinja2](https://github.com/pallets/jinja) | BSD-3-Clause |
| [python-multipart](https://github.com/Kludex/python-multipart) | Apache-2.0 |
| [HTTPX](https://github.com/encode/httpx) | BSD-3-Clause |
| [APScheduler](https://github.com/agronholm/apscheduler) | MIT |
| [segno](https://github.com/heuer/segno) | BSD-3-Clause |
| [setuptools](https://github.com/pypa/setuptools) | MIT |

## Trademarks

Docker and CasaOS are trademarks of their respective owners. They are mentioned only to describe what this
software works with; AppManager Pro is not affiliated with or endorsed by them. Icons and changelogs of the
apps you manage are loaded from their original sources at runtime and are not redistributed.
