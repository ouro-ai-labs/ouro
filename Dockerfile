# Multi-stage Docker build for ouro

FROM python:3.12-slim AS base

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy application code
COPY . .

# Install uv and package dependencies
RUN pip install --no-cache-dir uv
RUN uv pip install --system .

# Create a non-root user
RUN useradd -m -u 1000 agentuser && chown -R agentuser:agentuser /app
USER agentuser

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Entry point
ENTRYPOINT ["python", "main.py"]
CMD ["--help"]

# Usage:
# Build: docker build -t ouro .
# Run: docker run -it --rm -e ANTHROPIC_API_KEY=your_key ouro --task "Hello"
