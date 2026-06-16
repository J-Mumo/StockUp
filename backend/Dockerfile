# StockUp backend image: shared by api, worker, and beat services.
# Uses the official Playwright Python base so chromium + system deps are preinstalled
# (the marketscreener adapter falls back to playwright when HTTP is blocked).

FROM mcr.microsoft.com/playwright/python:v1.52.0-jammy

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Africa/Nairobi

WORKDIR /app

# tzdata so the EAT-based celery beat schedule resolves correctly
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends tzdata \
    && ln -sf /usr/share/zoneinfo/Africa/Nairobi /etc/localtime \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Non-root user (playwright base ships with a 'pwuser', reuse it)
RUN mkdir -p /app/data/annual_reports /app/data/marketscreener_prices /app/data/tv_prices \
    && chown -R pwuser:pwuser /app

USER pwuser

EXPOSE 8000

# Default command is the API. Compose overrides it for worker/beat.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
