"""Tải trước mô hình nhận diện khuôn mặt (YuNet + SFace, khoảng 39 MB) về FACE_MODEL_DIR.

Chạy:  python -m scripts.download_face_models
Không chạy thì máy chủ tự tải ở lần đăng ký / đăng nhập Face ID đầu tiên (lần đó sẽ chậm vài giây).
"""
from app.services import face

if __name__ == "__main__":
    for key, path in face.ensure_models().items():
        print(f"{key}: {path}")
