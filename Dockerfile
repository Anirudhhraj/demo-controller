FROM python:3.11-slim

WORKDIR /app

# Install deps first (better Docker layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY app/ ./app/
COPY demos.yaml .

# Cloud Run injects PORT; default to 8080 for local docker run
ENV PORT=8080
ENV PYTHONUNBUFFERED=1

# Shell form so $PORT expands at runtime
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}