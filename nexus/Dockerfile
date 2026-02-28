FROM python:3.11-slim
WORKDIR /app
COPY server.py .
EXPOSE 5001
HEALTHCHECK --interval=30s --timeout=3s \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:5001/api/status')" || exit 1
CMD ["python3", "server.py", "--host", "0.0.0.0", "--port", "5001"]
