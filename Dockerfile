FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY scanner/requirements.txt /app/scanner/requirements.txt
COPY scorer/requirements.txt /app/scorer/requirements.txt
COPY api/requirements.txt /app/api/requirements.txt

RUN pip install --no-cache-dir \
    -r scanner/requirements.txt \
    -r scorer/requirements.txt \
    -r api/requirements.txt

COPY . /app

# Default: run the API
CMD ["python", "api/main.py"]
