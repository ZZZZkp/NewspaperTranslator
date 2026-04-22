FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY docs ./docs
COPY tests ./tests

ENV PYTHONPATH=/app/src

CMD ["python", "-m", "http.server", "8000", "--bind", "0.0.0.0", "--directory", "/app/docs"]
