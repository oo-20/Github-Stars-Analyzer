FROM python:3.12-slim

WORKDIR /app

# 安装依赖
COPY src/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制源码
COPY src/ ./src/
# 复制缓存数据（如已存在）
COPY cached_data.json* ./

EXPOSE 5000

CMD ["python", "src/app.py"]
