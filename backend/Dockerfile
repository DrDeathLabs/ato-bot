FROM python:3.11-slim@sha256:90744cff8f32887f075c47d747a173ff333e9e98801667af93c357fa9f5e28ff

# System deps for document parsing
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir --constraint constraints.txt --upgrade "pip>=26.0" "setuptools>=83.0.0" "wheel>=0.46.2"
ARG TORCH_VERSION=2.9.1
RUN pip install --no-cache-dir --constraint constraints.txt --index-url https://download.pytorch.org/whl/cpu "torch==${TORCH_VERSION}"
RUN pip install --no-cache-dir --constraint constraints.txt -r requirements.txt
RUN python -m pip check && python -m pip uninstall --yes pip

COPY . .

RUN addgroup --system atobot && adduser --system --ingroup atobot --home /app atobot \
    && mkdir -p uploads outputs \
    && chown -R atobot:atobot /app

USER atobot

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
