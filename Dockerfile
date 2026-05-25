# --- Stage 1: Build Frontend ---
FROM node:18-slim AS frontend-builder
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# --- Stage 2: Final Image ---
FROM python:3.9-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies (including Nginx)
RUN if [ -f /etc/apt/sources.list ]; then \
        sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list && \
        sed -i 's/security.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list; \
    elif [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources && \
        sed -i 's/security.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources; \
    fi && \
    apt-get update && apt-get install -y --no-install-recommends \
    curl \
    nginx \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# Copy project files (respects .dockerignore)
COPY . .

# Copy built frontend assets
# We copy the whole dist folder to /app/frontend/dist to align with local dev structure
COPY --from=frontend-builder /frontend/dist /app/frontend/dist

# Configure Nginx
COPY nginx.conf /etc/nginx/sites-available/default
# Ensure Nginx runs in foreground if we were running it alone, but we will run it via entrypoint script
# Remove default nginx site if it exists (though we overwrote default above)

# Create necessary directories
RUN mkdir -p state logs

# Set environment variable for collectstatic
ENV WHITENOISE_MANIFEST_STRICT=False

# Collect static files
RUN python manage.py collectstatic --noinput --clear

# Setup entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
