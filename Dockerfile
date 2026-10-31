# ==============================================================================
# Dockerfile for Render Cloud Deployment (E-Commerce Arbitrage & Sourcing Bot)
# ==============================================================================
# Uses Microsoft's official Playwright Python image based on Ubuntu Jammy.
# Includes pre-installed Chromium, media codecs, fonts, and stealth dependencies.
# ==============================================================================

FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

# Set production environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive \
    HEADLESS=true \
    PORT=10000

# Set working directory
WORKDIR /app

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Ensure Playwright browser binaries are present
RUN playwright install chromium

# Copy application code
COPY . .

# Expose Render web service health check port
EXPOSE 10000

# Start interactive Telegram daemon with integrated Render health check server
CMD ["python", "bot_service.py"]
