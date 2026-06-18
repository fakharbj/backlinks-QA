FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      build-essential \
      curl \
      fonts-dejavu \
      libffi-dev \
      libgdk-pixbuf-2.0-0 \
      libpango-1.0-0 \
      libpangoft2-1.0-0 \
      libcairo2 \
      shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements.txt
COPY requirements-dev.txt requirements-dev.txt
RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && playwright install --with-deps chromium

COPY alembic.ini alembic.ini
COPY alembic alembic
COPY app app
COPY scripts scripts

RUN chmod +x scripts/entrypoint.sh \
    && useradd --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app /ms-playwright

USER appuser
EXPOSE 8000
ENTRYPOINT ["scripts/entrypoint.sh"]
CMD ["gunicorn", "app.main:app", "-k", "uvicorn.workers.UvicornWorker", "-w", "3", "-b", "0.0.0.0:8000"]

FROM runtime AS dev
USER root
RUN pip install -r requirements-dev.txt
USER appuser
