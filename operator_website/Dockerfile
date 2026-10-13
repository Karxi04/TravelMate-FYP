FROM python:3.11-slim
WORKDIR /app
COPY operator_website/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY operator_website/ /app/operator_website/
COPY portal_security_config.py request_rate_limit.py /app/
WORKDIR /app/operator_website
ENV PORT=8080
CMD ["sh", "-c", "gunicorn 'app:app' --bind 0.0.0.0:${PORT} --workers 2 --threads 4 --timeout 120"]
