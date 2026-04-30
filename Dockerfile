FROM python:3.11-slim

ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG ALL_PROXY
ARG NO_PROXY

ENV HTTP_PROXY=${HTTP_PROXY} \
    HTTPS_PROXY=${HTTPS_PROXY} \
    ALL_PROXY=${ALL_PROXY} \
    NO_PROXY=${NO_PROXY}

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY README.md ./
COPY src ./src
COPY docs ./docs
COPY tests ./tests

ENV PYTHONPATH=/app/src

CMD ["python", "-m", "newspaper_translator.web"]
