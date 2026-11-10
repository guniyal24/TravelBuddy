FROM python:3.12-slim
WORKDIR /srv
ENV PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY mcp_server ./mcp_server
COPY ingest ./ingest
COPY data/curated ./data/curated
COPY data/seeds ./data/seeds
EXPOSE 8000
# Trust the host's proxy for X-Forwarded-For so per-IP guest limits see the visitor's address.
CMD ["sh", "-c", "uvicorn app.api.asgi:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
