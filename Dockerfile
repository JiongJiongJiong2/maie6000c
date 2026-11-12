FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY services /app/services
COPY web/index.html web/styles.css web/app.js web/api.js web/store.js web/meme50.js /app/web/
COPY scripts /app/scripts
COPY alembic /app/alembic
COPY alembic.ini /app/alembic.ini

RUN pip install --upgrade pip && pip install -e ".[search]"

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --home-dir /app --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /data/media /data/models \
    && chown -R app:app /data

USER 10001:10001

CMD ["uvicorn", "services.api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Only the inference worker installs the local model runtime.
FROM base AS worker
USER root
RUN python -m pip install -e ".[search,retrieval]"
USER 10001:10001

# This target receives no DB credentials, model keys, media volume or private network.
FROM base AS media-fetch
CMD ["python", "-m", "services.retrieval.public_fetch"]

FROM base AS api
