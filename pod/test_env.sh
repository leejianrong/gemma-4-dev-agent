#!/usr/bin/env bash
# Install the test stack into the pod's Python at the versions in the competition's Kaggle image
# (read from a CPU kernel on that image, 2026-11-12: Python 3.12.13).
# The sandbox venv sees the host's site-packages, so pytest and the repositories' test dependencies
# must live there. fastapi and requests are the repositories under test; /workspace shadows them.
set -euo pipefail
python3 -m pip install --quiet --disable-pip-version-check \
  pytest==8.4.2 pluggy==1.6.0 anyio==4.13.0 httpx==0.28.1 httpcore==1.0.9 h11==0.16.0 \
  starlette==0.52.1 fastapi==0.136.1 pydantic==2.12.3 pydantic_core==2.41.4 annotated-types==0.7.0 \
  Jinja2==3.1.6 SQLAlchemy==2.0.49 Flask==3.1.3 Werkzeug==3.1.8 click==8.3.3 typer==0.24.2 \
  rich==13.9.4 urllib3==2.5.0 requests==2.32.4 typing_extensions==4.15.0 \
  python-multipart==0.0.26 email-validator==2.3.0 orjson==3.11.8 ujson==5.13.0 PyYAML==6.0.3 \
  itsdangerous==2.2.0 uvicorn==0.46.0 aiofiles==22.1.0 PyJWT==2.12.1 python-dotenv==1.2.2 \
  MarkupSafe==3.0.3 greenlet==3.4.0
python3 -m pip list --format=freeze 2>/dev/null | grep -iE '^(pytest|anyio|httpx|starlette|pydantic|sqlalchemy|flask)=='
