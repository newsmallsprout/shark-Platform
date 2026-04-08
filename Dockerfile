# --- Stage 1: Build Frontend ---
FROM node:18-slim AS frontend-builder
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./
# legacy-peer-deps: echarts-gl peer is echarts@5; project uses echarts@6 (see frontend/.npmrc)
RUN npm install --legacy-peer-deps
COPY frontend/ ./
RUN npm run build

# --- Stage 2: Final Image ---
# 镜像可直接作为 Kubernetes Deployment 运行；Pod 内会自动出现 KUBERNETES_SERVICE_HOST，便于 AIOPS_DEPLOYMENT_MODE 推断为 kubernetes。
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

# Nginx：log_format 须在 http 块，Debian 默认 include conf.d/*.conf
COPY nginx-log-format.conf /etc/nginx/conf.d/00-shark-log-format.conf
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
