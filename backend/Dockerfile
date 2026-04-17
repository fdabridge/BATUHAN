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
# Unprivileged user for security
RUN useradd --no-create-home --shell /bin/false batuhan \
    && mkdir -p /app/storage /app/prompts \
    && chown -R batuhan:batuhan /app
USER batuhan

# API port
EXPOSE 8000

# Default command: start the FastAPI API server.
# Override in docker-compose for the Celery worker.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

