FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    RATIFIED_FALKOR_HOST=falkordb \
    RATIFIED_FALKOR_PORT=6379 \
    RATIFIED_GRAPH=ratified \
    RATIFIED_DATA_DIR=/app/data \
    RATIFIED_CACHE_DIR=/app/cache/http \
    RATIFIED_LLM=off

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

COPY data ./data
COPY cache ./cache

EXPOSE 8000

CMD ["sh", "-c", "python -m ratified && exec uvicorn ratified.app:app --host 0.0.0.0 --port 8000"]
