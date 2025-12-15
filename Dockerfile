FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install Python dependencies via PEP 517 build (poetry-core backend)
COPY pyproject.toml poetry.lock README.md /app/
COPY src /app/src
COPY scripts /app/scripts
RUN chmod +x /app/scripts/run_aggregator_loop.sh
RUN pip install --no-cache-dir .

# Default env paths inside container
ENV DATA_DIR=/app/data \
    DB_PATH=/app/data/presence.db

EXPOSE 18080

CMD ["python", "-m", "unhinged_spyware.api"]
