FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Chromium for server-side PDF export. --with-deps pulls the OS libraries it needs; the browser is
# installed system-wide so the non-root appuser created below can launch it.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN playwright install --with-deps chromium

COPY . .

# Run as a non-root user: create it, ensure a writable logs dir, own the app tree.
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p logs \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
