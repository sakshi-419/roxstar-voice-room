# Multi-stage production container for LiveKit Cloud Agent
FROM python:3.12-slim AS runtime

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv package manager
RUN pip install --no-cache-dir uv

# Copy dependency specifications and sync
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy application source code
COPY . .

ENV PYTHONUNBUFFERED=1

# Production command for LiveKit Cloud Agent worker
CMD ["uv", "run", "python", "agent.py", "start"]
