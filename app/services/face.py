"""Nhận diện khuôn mặt cho đăng nhập Face ID, chạy hoàn toàn ở máy chủ bằng OpenCV.

- YuNet: tìm khuôn mặt và 5 điểm mốc (mắt, mũi, khóe miệng) trong ảnh.
- SFace: căn chỉnh khuôn mặt theo điểm mốc rồi tính vector đặc trưng 128 chiều.
Hai khuôn mặt cùng một người khi độ giống cosine của hai vector >= ngưỡng (SFace khuyến nghị 0.363).

Trình duyệt chỉ gửi ảnh chụp từ webcam, vector luôn do máy chủ tính, nên không giả được bằng cách gửi vector bịa.

Kiểm tra người thật (liveness, xem routers/auth.py): yêu cầu quay đầu theo thứ tự ngẫu nhiên. Độ quay đầu (yaw) ước lượng
từ vị trí đầu mũi so với hai mắt. Mặt thật là khối 3D nên mũi lệch hẳn sang một bên khi quay; ảnh in là mặt phẳng,
nghiêng tờ ảnh chỉ làm cả khuôn mặt hẹp lại đều nhau, mũi vẫn nằm giữa hai mắt nên không qua được bước quay đầu.
"""
import hashlib
import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from app.config import settings

log = logging.getLogger(__name__)

_ZOO = "https://github.com/opencv/opencv_zoo/raw/main/models"
MODELS = {
    "detector": ("face_detection_yunet_2023mar.onnx", f"{_ZOO}/face_detection_yunet/face_detection_yunet_2023mar.onnx",
                 "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"),
    "recognizer": ("face_recognition_sface_2021dec.onnx", f"{_ZOO}/face_recognition_sface/face_recognition_sface_2021dec.onnx",
                   "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79"),
}
MAX_SIDE = 800       # ảnh lớn hơn thì thu nhỏ trước khi tìm mặt cho nhanh
MIN_FACE_PX = 60     # khuôn mặt nhỏ hơn (đứng quá xa camera) thì ảnh đặc trưng kém tin cậy
DETECT_SCORE = 0.8

_lock = threading.Lock()
_models = None


class FaceError(Exception):
    """Ảnh không dùng được: không có mặt, nhiều mặt, mặt quá nhỏ, ảnh hỏng. Thông báo hiển thị cho người dùng."""


class FaceUnavailable(Exception):
    """Máy chủ chưa cài OpenCV hoặc không tải được mô hình."""


@dataclass
class FaceScan:
    embedding: list[float]  # vector đặc trưng đã chuẩn hóa độ dài 1
    yaw: float  # độ lệch của mũi so với giữa hai mắt, tính theo khoảng cách hai mắt. 0 = nhìn thẳng,
    # dương = mũi lệch sang phải ảnh gốc (người quay sang trái của họ, trên khung camera lật gương thấy quay sang trái)


def installed() -> bool:
    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
    except ImportError:
        return False
    return True


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_models() -> dict[str, Path]:
    """Tải mô hình về FACE_MODEL_DIR nếu chưa có, kiểm tra SHA-256 để chắc file đúng và còn nguyên."""
    import httpx

    folder = settings.FACE_MODEL_DIR
    folder.mkdir(parents=True, exist_ok=True)
    paths = {}
    for key, (name, url, digest) in MODELS.items():
        path = folder / name
        if not path.exists() or _sha256(path) != digest:
            log.info("Đang tải mô hình Face ID %s", name)
            tmp = path.with_suffix(".part")
            try:
                with httpx.stream("GET", url, follow_redirects=True, timeout=120) as r:
                    r.raise_for_status()
                    with tmp.open("wb") as f:
                        for chunk in r.iter_bytes():
                            f.write(chunk)
            except httpx.HTTPError as e:
                tmp.unlink(missing_ok=True)
                raise FaceUnavailable(f"Không tải được mô hình nhận diện khuôn mặt ({name}): {e}") from e
            if _sha256(tmp) != digest:
                tmp.unlink(missing_ok=True)
                raise FaceUnavailable(f"Mô hình nhận diện khuôn mặt tải về bị sai mã kiểm tra ({name})")
            tmp.replace(path)
        paths[key] = path
    return paths


def _load():
    global _models
    if _models is None:
        if not installed():
            raise FaceUnavailable("Máy chủ chưa cài OpenCV (pip install opencv-python-headless numpy)")
        import cv2

        paths = ensure_models()
        detector = cv2.FaceDetectorYN.create(str(paths["detector"]), "", (320, 320), DETECT_SCORE)
        recognizer = cv2.FaceRecognizerSF.create(str(paths["recognizer"]), "")
        _models = (detector, recognizer)
    return _models


def _yaw(face) -> float:
    import numpy as np

    eyes = sorted([np.array(face[4:6]), np.array(face[6:8])], key=lambda e: e[0])  # mắt bên trái ảnh trước
    nose = np.array(face[8:10])
    axis = eyes[1] - eyes[0]
    dist = float(np.linalg.norm(axis))
    if not dist:
        return 0.0
    # chiếu lên trục nối hai mắt nên nghiêng đầu (xoay trong mặt phẳng ảnh) không ảnh hưởng
    return float(np.dot(nose - (eyes[0] + eyes[1]) / 2, axis / dist) / dist)


def embed(image_bytes: bytes) -> list[float]:
    """Ảnh (JPEG/PNG/WebP) -> vector đặc trưng đã chuẩn hóa độ dài 1. Ảnh phải có đúng một khuôn mặt."""
    return analyze(image_bytes).embedding


def analyze(image_bytes: bytes) -> FaceScan:
    """Tìm đúng một khuôn mặt trong ảnh, trả về vector đặc trưng và độ quay đầu."""
    import cv2
    import numpy as np

    with _lock:  # đối tượng mạng nơ-ron của OpenCV không an toàn khi nhiều luồng dùng chung
        detector, recognizer = _load()
        img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise FaceError("Ảnh không hợp lệ")
        h, w = img.shape[:2]
        if max(h, w) > MAX_SIDE:
            scale = MAX_SIDE / max(h, w)
            img = cv2.resize(img, (round(w * scale), round(h * scale)))
            h, w = img.shape[:2]
        detector.setInputSize((w, h))
        _, faces = detector.detect(img)
        if faces is None or len(faces) == 0:
            raise FaceError("Không thấy khuôn mặt, hãy nhìn thẳng vào camera và đủ sáng")
        if len(faces) > 1:
            raise FaceError("Có nhiều khuôn mặt trong khung hình, chỉ để một người")
        face = faces[0]
        if min(face[2], face[3]) < MIN_FACE_PX:
            raise FaceError("Khuôn mặt quá nhỏ, hãy lại gần camera hơn")
        feature = recognizer.feature(recognizer.alignCrop(img, face)).flatten().astype(np.float64)
    norm = np.linalg.norm(feature)
    if not norm:
        raise FaceError("Không trích được đặc trưng khuôn mặt")
    return FaceScan(embedding=(feature / norm).tolist(), yaw=_yaw(face))


def similarity(a: list[float], b: list[float]) -> float:
    """Độ giống cosine của hai vector đã chuẩn hóa (1 = trùng khớp)."""
    return float(sum(x * y for x, y in zip(a, b)))
