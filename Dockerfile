FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends git curl && rm -rf /var/lib/apt/lists/*
RUN useradd -m -u 1000 appuser
WORKDIR /build
COPY pyproject.toml .
COPY src/ ./src/
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir ".[all]"
WORKDIR /app
USER appuser
ENTRYPOINT ["convaier"]
CMD ["--help"]
