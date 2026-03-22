# BATUHAN — Backend Dockerfile
# Builds a production-ready image for the FastAPI API server and Celery worker.
# Both services use the same image; the CMD differs in docker-compose.yml.

FROM python:3.12-slim

# -----------------------------------------------------------------------
# System dependencies
# -----------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Tesseract OCR engine
    tesseract-ocr \
    tesseract-ocr-eng \
    # PDF rendering (PyMuPDF / pdfplumber)
    libmupdf-dev \
    # Image support (Pillow)
    libjpeg-dev \
    libpng-dev \
    libtiff-dev \
    # Build tools
    gcc \
    && rm -rf /var/lib/apt/lists/*

# -----------------------------------------------------------------------
# Python environment
# -----------------------------------------------------------------------
WORKDIR /app

# Copy and install requirements before the rest of the source so this
# layer is cached unless requirements.txt changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# -----------------------------------------------------------------------
# Application source
# -----------------------------------------------------------------------
COPY . .

# -----------------------------------------------------------------------
# Runtime configuration
# -----------------------------------------------------------------------
# Unprivileged user for security
RUN useradd --no-create-home --shell /bin/false batuhan \
    && mkdir -p /app/storage /app/prompts \
    && chown -R batuhan:batuhan /app
USER batuhan

# API port
EXPOSE 8000

# Default command: start the FastAPI API server.
# Override in docker-compose for the Celery worker.
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]

