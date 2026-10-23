FROM python:3.13-slim

WORKDIR /app
# Build from the repository root. Copy only package inputs, never local workspaces.
COPY pyproject.toml README.md LICENSE NOTICE.md ./
COPY src/ ./src/
RUN python -m pip install --no-cache-dir '.[mcp]' \
    && mkdir -p /data/zing \
    && chown -R 65532:65532 /data/zing

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ZING_HOME=/data/zing \
    UOINK_URL=http://127.0.0.1:1 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

USER 65532:65532
CMD ["zing", "serve-mcp"]
