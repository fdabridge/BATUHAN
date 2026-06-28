# BATUHAN — Backend Dockerfile
# Builds a production-ready image for the FastAPI API server and Celery worker.
# Both services use the same image; the CMD differs in docker-compose.yml.

FROM python:3.12-slim

# -----------------------------------------------------------------------
# System dependencies
# -----------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Tesseract OCR engine + language packs
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-tur \
    # PDF rendering (PyMuPDF / pdfplumber)
    libmupdf-dev \
    # Image support (Pillow)
    libjpeg-dev \
    libpng-dev \
    libtiff-dev \
    # Build tools
    gcc \
    # LibreOffice headless — DOCX → PDF conversion (Prompt 23)
    libreoffice-writer \
    libreoffice-calc \
    fonts-liberation \
    fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*

# -----------------------------------------------------------------------
# Python environment
# -----------------------------------------------------------------------
WORKDIR /app

# Ensure all backend modules (parsers, pipeline, safety, etc.) are importable
# by every process started from this image — uvicorn, celery master, and all
# celery worker child processes alike.  WORKDIR only sets the shell's cwd; it
# does NOT add the directory to Python's sys.path.  PYTHONPATH does.
ENV PYTHONPATH=/app

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
# NOTE: we do NOT create a non-root user here.
# Railway Volumes are mounted root:root at container start; a non-root user
# cannot write to them.  Railway containers are already isolated so running
# as root inside the container is standard practice on that platform.
RUN mkdir -p /app/prompts

# API port
EXPOSE 8000

# Default command: start the FastAPI API server.
# Override in docker-compose for the Celery worker.
# mkdir -p ensures the root storage directory exists under the Volume mount
# (STORAGE_BASE_PATH=/data/storage in production; ./storage locally).
CMD ["sh", "-c", "mkdir -p ${STORAGE_BASE_PATH:-/app/storage} && uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]

