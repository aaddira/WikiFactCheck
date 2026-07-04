FROM python:3.13-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Create data directory for SQLite
RUN mkdir -p data

# Set FLASK_APP for CLI commands
ENV FLASK_APP=main.py

# Expose port
EXPOSE 5000

# Run migrations, then start gunicorn
CMD ["sh", "-c", "flask db upgrade && gunicorn --bind 0.0.0.0:5000 --timeout 60 --workers 2 main:app"]
