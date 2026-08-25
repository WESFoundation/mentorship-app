# Base Python Image
FROM python:3.10-slim

# Prevent Python from writing pyc files and enable unbuffered logging
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=5000

# Set working directory
WORKDIR /app

# Install essential system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements.txt and install Python dependencies
COPY requirements.txt /app/
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy all project files into container
COPY . /app/

# Ensure upload directory and instance directory exist with proper permissions
RUN mkdir -p static/uploads instance && \
    chmod -R 777 instance static/uploads

# Convert line endings and make entrypoint script executable
RUN sed -i 's/\r$//' /app/entrypoint.sh && \
    chmod +x /app/entrypoint.sh

# Declare persistent volumes for database and user uploads
VOLUME ["/app/instance", "/app/static/uploads"]

# Expose app port
EXPOSE 5000

# Run entrypoint script
ENTRYPOINT ["/app/entrypoint.sh"]
