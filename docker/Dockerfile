FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY backend/requirements.txt ./backend/requirements.txt
RUN python -m pip install --upgrade pip && \
    pip install --no-cache-dir -r backend/requirements.txt

COPY . .

RUN useradd --create-home --uid 10001 appuser && \
    mkdir -p /app/data && \
    chmod +x /app/docker/entrypoint.sh && \
    chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

CMD ["/app/docker/entrypoint.sh"]
