FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app
# Tesseract para OCR de PDFs escaneados (português + inglês)
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-por tesseract-ocr-eng \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt
COPY . .
