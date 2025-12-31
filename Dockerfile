FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 jobsniper && \
    chown -R jobsniper:jobsniper /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories with proper permissions
RUN mkdir -p /app/data /app/logs && \
    chown -R jobsniper:jobsniper /app/data /app/logs

# Switch to non-root user
USER jobsniper

# Run the application
CMD ["python", "main.py"]
