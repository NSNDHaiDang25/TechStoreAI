FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# Font Unicode để xuất PDF tiếng Việt có dấu
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY prompts ./prompts
COPY static ./static
COPY scripts ./scripts
# Mô hình Face ID tải sẵn lúc build để lần đăng nhập đầu không phải chờ tải
RUN python -m scripts.download_face_models

EXPOSE 8000
# Lần đầu chạy: tự tạo dữ liệu mẫu nếu chưa có CSDL
CMD ["sh", "-c", "[ -f data/sales.db ] || python -m scripts.seed; uvicorn app.main:app --host 0.0.0.0 --port 8000"]
