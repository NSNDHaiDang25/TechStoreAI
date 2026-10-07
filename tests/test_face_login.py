"""Đăng nhập Face ID (chủ cửa hàng, quản trị viên) kèm kiểm tra người thật (liveness).

Phần lớn test thay face.analyze bằng hàm giả: ảnh là chuỗi "tên:yaw" (khuôn mặt nào, quay đầu bao nhiêu)
để chạy nhanh, không cần OpenCV. Test cuối dùng mô hình thật với ảnh mẫu trong scripts/face_samples,
máy chưa có OpenCV / mô hình thì bỏ qua.
"""
from pathlib import Path

import pytest

from app.config import settings
from app.routers import auth as auth_router
from app.services import face

# Vector giả 4 chiều đã chuẩn hóa: "owner" và "owner2" rất giống nhau (0.8), "admin" và "stranger" khác hẳn
FACES = {
    "owner": [1.0, 0.0, 0.0, 0.0],
    "owner2": [0.8, 0.6, 0.0, 0.0],
    "stranger": [0.0, 0.0, 1.0, 0.0],
    "admin": [0.0, 0.0, 0.0, 1.0],
}
TURN = {"center": 0.0, "left": 0.4, "right": -0.4}


def fake_analyze(raw: bytes):
    name, _, yaw = raw.decode().partition(":")
    if name == "noface":
        raise face.FaceError("Không thấy khuôn mặt, hãy nhìn thẳng vào camera và đủ sáng")
    return face.FaceScan(embedding=FACES[name], yaw=float(yaw or 0))


@pytest.fixture(autouse=True)
def _fake_face(monkeypatch):
    monkeypatch.setattr(face, "analyze", fake_analyze)
    monkeypatch.setattr(face, "installed", lambda: True)
    auth_router._face_failures.clear()
    auth_router._face_sessions.clear()
    yield
    auth_router._face_failures.clear()
    auth_router._face_sessions.clear()


def enroll(client, h, img=b"owner", password="owner123"):
    return client.post("/api/auth/face", headers=h, data={"password": password},
                       files={"file": ("f.jpg", img, "image/jpeg")})


def start(client):
    r = client.post("/api/auth/face-login/start")
    assert r.status_code == 200, r.text
    return r.json()


def frame(client, sid, who, yaw=0.0):
    return client.post("/api/auth/face-login/frame", data={"session": sid},
                       files={"file": ("f.jpg", f"{who}:{yaw}".encode(), "image/jpeg")})


def full_flow(client, who):
    """Làm đúng thử thách: nhìn thẳng rồi quay đầu theo đúng thứ tự máy chủ yêu cầu."""
    s = start(client)
    r = None
    for step in s["steps"]:
        r = frame(client, s["session"], who, TURN[step])
        if r.status_code != 200 or r.json()["done"]:
            break
    return r


def test_status_hidden_until_enrolled(client, owner_h):
    assert client.get("/api/auth/face-login/status").json() == {"enabled": False}
    assert enroll(client, owner_h).status_code == 200
    assert client.get("/api/auth/face-login/status").json() == {"enabled": True}


def test_enroll_requires_password_and_role(client, owner_h, staff_h):
    assert enroll(client, owner_h, password="sai-mat-khau").status_code == 400
    assert enroll(client, staff_h, password="staff123").status_code == 403  # nhân viên không dùng Face ID
    r = enroll(client, owner_h)
    assert r.status_code == 200 and r.json()["count"] == 1
    assert client.get("/api/auth/face", headers=owner_h).json()["count"] == 1


def test_enroll_rejects_image_without_face(client, owner_h):
    assert enroll(client, owner_h, img=b"noface").status_code == 422
    assert client.get("/api/auth/face", headers=owner_h).json()["count"] == 0


def test_challenge_is_center_then_random_turns(client, owner_h):
    enroll(client, owner_h)
    s = start(client)
    assert s["steps"][0] == "center" and sorted(s["steps"][1:]) == ["left", "right"]


def test_full_flow_shows_who_and_logs_in(client, owner_h):
    enroll(client, owner_h)
    s = start(client)
    r = frame(client, s["session"], "owner2").json()  # nhìn thẳng: nhận diện xong, biết là ai
    assert r["done"] is False and r["step"] == 1
    assert r["user"] == {"full_name": "Chủ", "role": "owner"}
    for step in s["steps"][1:]:
        r = frame(client, s["session"], "owner2", TURN[step]).json()
    assert r["done"] is True
    assert r["user"]["username"] == "owner" and r["user"]["role"] == "owner"
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {r['access_token']}"})
    assert me.status_code == 200 and me.json()["role"] == "owner"


def test_owner_and_admin_each_get_their_own_account(client, owner_h, admin_h):
    enroll(client, owner_h)
    assert enroll(client, admin_h, img=b"admin", password="admin123").status_code == 200
    assert full_flow(client, "admin").json()["user"]["role"] == "admin"
    assert full_flow(client, "owner").json()["user"]["role"] == "owner"


def test_photo_never_turns_so_never_logs_in(client, owner_h, monkeypatch):
    """Ảnh in giơ trước camera: nhận diện được nhưng không quay đầu được, hết lượt thì thất bại."""
    enroll(client, owner_h)
    monkeypatch.setattr(auth_router, "FACE_SESSION_MAX_FRAMES", 6)
    s = start(client)
    for _ in range(6):
        r = frame(client, s["session"], "owner")
        assert r.status_code == 200 and r.json()["done"] is False
    assert frame(client, s["session"], "owner").status_code == 410
    assert sum(len(q) for q in auth_router._face_failures.values()) == 1


def test_wrong_direction_does_not_advance(client, owner_h):
    enroll(client, owner_h)
    s = start(client)
    frame(client, s["session"], "owner")
    wrong = "right" if s["steps"][1] == "left" else "left"
    r = frame(client, s["session"], "owner", TURN[wrong]).json()
    assert r["step"] == 1 and r["done"] is False


def test_face_swapped_during_turns_fails(client, owner_h):
    """Giơ ảnh chủ cửa hàng lúc nhìn thẳng rồi tự quay đầu bằng mặt mình: bị phát hiện đổi khuôn mặt."""
    enroll(client, owner_h)
    s = start(client)
    frame(client, s["session"], "owner")
    for _ in range(auth_router.FACE_MAX_SWAPS - 1):
        assert frame(client, s["session"], "stranger", TURN[s["steps"][1]]).status_code == 200
    r = frame(client, s["session"], "stranger", TURN[s["steps"][1]])
    assert r.status_code == 401 and "access_token" not in r.json()


def test_stranger_rejected(client, owner_h):
    enroll(client, owner_h)
    s = start(client)
    for _ in range(auth_router.FACE_MAX_MISSES - 1):
        assert frame(client, s["session"], "stranger").json()["user"] is None
    assert frame(client, s["session"], "stranger").status_code == 401
    assert frame(client, s["session"], "owner").status_code == 410  # phiên đã hủy


def test_liveness_can_be_turned_off(client, owner_h, admin_h):
    enroll(client, owner_h)
    r = client.put("/api/settings", headers=admin_h, json={"values": {"face_liveness_enabled": False}})
    assert r.status_code == 200
    s = start(client)
    assert s["steps"] == ["center"]
    assert frame(client, s["session"], "owner").json()["done"] is True


def test_start_without_enrollment(client):
    assert client.post("/api/auth/face-login/start").status_code == 400


def test_unknown_session(client, owner_h):
    enroll(client, owner_h)
    assert frame(client, "khong-ton-tai", "owner").status_code == 410


def test_owner_demoted_to_staff_cannot_use_face(client, owner_h, db):
    enroll(client, owner_h)
    from app.models import User
    db.query(User).filter_by(username="owner").one().role = "staff"
    db.commit()
    s = start(client)
    for _ in range(auth_router.FACE_MAX_MISSES - 1):
        frame(client, s["session"], "owner")
    assert frame(client, s["session"], "owner").status_code == 401


def test_locked_account_refused(client, owner_h, db):
    enroll(client, owner_h)
    from app.models import User
    db.query(User).filter_by(username="owner").one().is_active = False
    db.commit()
    s = start(client)
    assert frame(client, s["session"], "owner").status_code == 403


def test_rate_limited_after_many_failures(client, owner_h):
    enroll(client, owner_h)
    for _ in range(auth_router.FACE_MAX_FAIL):
        s = start(client)
        for _ in range(auth_router.FACE_MAX_MISSES):
            r = frame(client, s["session"], "stranger")
        assert r.status_code == 401
    assert client.post("/api/auth/face-login/start").status_code == 429


def test_face_login_can_be_disabled(client, owner_h, admin_h):
    enroll(client, owner_h)
    r = client.put("/api/settings", headers=admin_h, json={"values": {"face_login_enabled": False}})
    assert r.status_code == 200
    assert client.get("/api/auth/face-login/status").json() == {"enabled": False}
    assert client.post("/api/auth/face-login/start").status_code == 403


def test_threshold_setting(client, owner_h, admin_h):
    enroll(client, owner_h)
    # owner2 giống owner 0.8: nâng ngưỡng lên 0.85 thì không nhận ra
    r = client.put("/api/settings", headers=admin_h, json={"values": {"face_login_threshold": 0.85}})
    assert r.status_code == 200
    s = start(client)
    assert frame(client, s["session"], "owner2").json()["user"] is None


def test_delete_face(client, owner_h):
    enroll(client, owner_h)
    assert client.delete("/api/auth/face", headers=owner_h).status_code == 200
    assert client.get("/api/auth/face", headers=owner_h).json()["count"] == 0
    assert client.post("/api/auth/face-login/start").status_code == 400


SAMPLES = Path(__file__).resolve().parent.parent / "scripts" / "face_samples"


def _real_models_ready() -> bool:
    if not face.installed():
        return False
    return all((settings.FACE_MODEL_DIR / name).exists() for name, _, _ in face.MODELS.values())


@pytest.mark.skipif(not _real_models_ready() or not SAMPLES.exists(), reason="chưa có OpenCV hoặc mô hình Face ID")
def test_real_model(monkeypatch):
    monkeypatch.undo()  # dùng face.analyze thật
    import cv2

    owner = [face.analyze(p.read_bytes()) for p in sorted((SAMPLES / "chucuahang").glob("*"))]
    admin = [face.analyze(p.read_bytes()) for p in sorted((SAMPLES / "admin").glob("*"))]
    threshold = 0.40
    # cùng người: mỗi ảnh khớp ít nhất một ảnh khác của chính người đó
    for group in (owner, admin):
        for i, a in enumerate(group):
            assert max(face.similarity(a.embedding, b.embedding) for j, b in enumerate(group) if j != i) >= threshold
    # khác người: chủ cửa hàng và quản trị viên không bị nhận nhầm sang nhau
    assert max(face.similarity(a.embedding, b.embedding) for a in owner for b in admin) < threshold

    # độ quay đầu: ảnh nhìn thẳng gần 0, ảnh quay đầu vượt ngưỡng quay
    front, turned_a, turned_b = admin[2], admin[0], admin[1]
    assert abs(front.yaw) < auth_router.FACE_CENTER_YAW
    assert abs(turned_a.yaw) >= auth_router.FACE_TURN_YAW and abs(turned_b.yaw) >= auth_router.FACE_TURN_YAW
    assert turned_a.yaw * turned_b.yaw < 0  # hai ảnh quay về hai phía

    # ảnh in nghiêng đi (mặt phẳng bị nén ngang) vẫn là nhìn thẳng: không giả được bước quay đầu
    img = cv2.imread(str(SAMPLES / "admin" / "3.jpg"))
    for ratio in (0.5, 0.7):
        squeezed = cv2.resize(img, (int(img.shape[1] * ratio), img.shape[0]))
        _, buf = cv2.imencode(".jpg", squeezed)
        assert abs(face.analyze(buf.tobytes()).yaw) < auth_router.FACE_CENTER_YAW

    with pytest.raises(face.FaceError):  # ảnh sản phẩm không có khuôn mặt
        face.analyze(next((settings.STATIC_DIR / "img" / "products").glob("*.webp")).read_bytes())
