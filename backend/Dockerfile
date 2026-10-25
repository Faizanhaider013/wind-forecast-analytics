FROM python:3.13-slim

WORKDIR /app

# Install dependencies first to leverage Docker layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
# Tests and pytest config are included so the documented Docker test command
# (`docker compose run --rm backend pytest`) works without a separate image.
COPY tests ./tests
COPY pytest.ini ./pytest.ini

# Default location for the SQLite DB and cached raw responses. Compose mounts
# the host ./data here so ingested data persists and is visible on the host.
ENV WIND_DATA_DIR=/app/data

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
