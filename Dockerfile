# Use stable & production-friendly base image
FROM python:3.11-slim

# Prevent Python from writing .pyc files
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# psycopg Dependency
RUN apt-get update && apt-get install -y \
    libpq5 \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app.py requirements.txt .
COPY static/css/* static/css/
COPY static/img/* static/img/
COPY static/js/* static/js/
COPY templates/* templates/ 
# Expose Flask port
EXPOSE 8000

# Run the app
CMD ["python", "app.py"]

