# Ratatosk container image (ARCH-005 hardening: pinned base image digest,
# hash-verified dependencies, non-root user, health check).
# Update the digest deliberately: docker buildx imagetools inspect python:3.13-slim
FROM python:3.15-slim@sha256:94d3426f1def7db4a106a232ac121bfd975393e5dfd40a619b955fae45fe7913

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Exact, hash-pinned versions: a tampered or substituted package fails the install.
COPY requirements.lock .
RUN pip install --require-hashes -r requirements.lock

COPY app ./app
COPY cli ./cli
COPY frontend ./frontend
COPY migrations ./migrations
COPY alembic.ini ./

RUN useradd --system --uid 10001 --home-dir /app ratatosk \
 && mkdir -p /app/data /app/storage/encrypted /app/storage/tmp /app/storage/branding \
 && chown -R ratatosk:ratatosk /app/data /app/storage
USER ratatosk

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

# init_db runs the migrations and creates the first admin (idempotent).
# --proxy-headers: trust X-Forwarded-Proto from your reverse proxy so HSTS
# and secure cookies apply; restrict with FORWARDED_ALLOW_IPS.
CMD ["sh", "-c", "python -m app.init_db && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers"]
