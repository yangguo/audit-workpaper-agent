FROM python:3.12-slim

WORKDIR /app

ENV COZE_WORKSPACE_PATH=/app
ENV PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock ./

RUN pip install --no-cache-dir uv \
    && uv sync --frozen --no-dev \
    && uv cache clean

COPY src/ ./src/
COPY config/ ./config/

RUN mkdir -p /app/logs /app/assets/uploads

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/health')"

CMD ["python", "src/main.py", "-m", "http", "-p", "5000"]
