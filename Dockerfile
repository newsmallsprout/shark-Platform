FROM python:3.9-slim

WORKDIR /app

# 安装依赖
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 代码会在 docker-compose 中挂载，这里为了构建只需要基本结构
COPY app /app

# 启动 FastAPI
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
