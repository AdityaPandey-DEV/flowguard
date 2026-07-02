FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (Docker layer caching — if requirements.txt
# doesn't change, this layer is cached and pip install is skipped)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose Flask port
EXPOSE 5000

# Run the Flask application
CMD ["python", "app.py"]
