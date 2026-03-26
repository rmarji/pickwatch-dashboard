FROM python:3.11-slim

WORKDIR /app

# Install curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Copy application files
COPY api_client.py scoring.py picks.py server.py ./

# Create config directory
RUN mkdir -p /data/config

# Set environment
ENV PORT=8080
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/api/health || exit 1

CMD ["python3", "server.py"]
