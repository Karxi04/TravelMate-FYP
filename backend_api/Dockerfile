FROM python:3.11-slim
WORKDIR /app/backend_api
# Build from the repository root: docker build -f backend_api/Dockerfile .
COPY backend_api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend_api/ .
COPY request_rate_limit.py /app/request_rate_limit.py
ENV PORT=8080
CMD ["sh", "-c", "gunicorn 'app:create_app()' --bind 0.0.0.0:${PORT} --workers 2 --threads 4 --timeout 120"]
