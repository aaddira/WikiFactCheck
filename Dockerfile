FROM python:3.13-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Create data directories for SQLite (both local and persistent volume)
RUN mkdir -p /app/data /data

# Set FLASK_APP for CLI commands
ENV FLASK_APP=main.py

# Copy entrypoint script
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Expose port
EXPOSE 5000

# Run entrypoint script
ENTRYPOINT ["/app/entrypoint.sh"]
