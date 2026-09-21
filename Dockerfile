# syntax=docker/dockerfile:1
FROM python:3.11-slim

# Set environment variables for production execution
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080 \
    DATABASE_PATH=/app/data/edgepulse.db \
    GOOGLE_CLIENT_ID=508845137062-g24ukrhleck76s93hikuqld8qe53nrll.apps.googleusercontent.com

WORKDIR /app

# Copy project files
COPY . /app

# Ensure data directory exists for SQLite database
RUN mkdir -p /app/data

# Expose web service port
EXPOSE 8080

# Container liveness health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python3 -c "import urllib.request, os; urllib.request.urlopen('http://localhost:' + os.environ.get('PORT', '8080') + '/api/health')" || exit 1

# Run web application server
CMD ["python3", "web_app.py"]
