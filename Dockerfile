FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY README.md ./
COPY src ./src
COPY docs ./docs
COPY tests ./tests

ENV PYTHONPATH=/app/src

CMD ["python", "-m", "newspaper_translator.web"]
