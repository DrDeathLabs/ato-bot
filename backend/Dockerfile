FROM python:3.11-slim

# System deps for document parsing
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade "pip>=26.0" "wheel>=0.46.2"
ARG TORCH_VERSION=2.9.1
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu "torch==${TORCH_VERSION}"
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN addgroup --system atobot && adduser --system --ingroup atobot --home /app atobot \
    && mkdir -p uploads outputs \
    && chown -R atobot:atobot /app

USER atobot

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
