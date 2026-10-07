import copy

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import security
from app.ai.client import AIResult, ChatReply, get_ai_client
from app.database import Base, get_db, make_engine
from app.main import app
from app.models import Category, Customer, Product, User
from app.security import hash_password

# Mỗi test tạo 3 tài khoản: băm bcrypt ở mức thấp nhất (4) cho nhanh, thuật toán vẫn như khi chạy thật
security.BCRYPT_ROUNDS = 4


class FakeAI:
    """Client AI giả: trả về phản hồi định sẵn hoặc ném lỗi, đồng thời ghi lại prompt đã gửi."""

    def __init__(self):
        self.enabled = True
        self.model = "fake-model"
        self.response: str | Exception = '{"answer": "ok", "suggestions": []}'
        # Nếu có: generate() lần lượt trả từng phần tử (chuỗi hoặc Exception), hết thì dùng self.response
        self.responses: list = []
        self.calls: list[dict] = []
        # Kịch bản cho chat() (trợ lý đa năng), mỗi lượt là: chuỗi = trả lời văn bản,
        # list = danh sách lệnh gọi công cụ [{"name": ..., "args": {...}}], Exception = lỗi
        self.chat_script: list = []
        self.available = True  # còn model nào gọi được không (client thật: has_available_model)

    def generate(self, system, user, *, json_mode=False, temperature=0.3, feature="unknown"):
        self.calls.append({"system": system, "user": user, "json_mode": json_mode, "feature": feature})
        step = self.responses.pop(0) if self.responses else self.response
        if isinstance(step, Exception):
            raise step
        return AIResult(text=step, model=self.model, latency_ms=5)

    def has_available_model(self):
        return self.available

    def status(self):
        return {"active_model": self.model if self.available else None,
                "models": [{"model": self.model, "available": self.available, "reason": None, "until": None}]}

    def chat(self, system, contents, *, tools, temperature=0.3, force_text=False, feature="unknown", model=None):
        self.calls.append({"system": system, "contents": copy.deepcopy(contents), "tools": tools,
                           "force_text": force_text, "feature": feature, "model": model})
        step = self.chat_script.pop(0) if self.chat_script else "ok"
        if isinstance(step, Exception):
            raise step
        if isinstance(step, list):
            return ChatReply(text="", calls=step, content={"role": "model", "parts": [{"functionCall": c} for c in step]},
                             model=self.model, latency_ms=5)
        return ChatReply(text=step, calls=[], content={"role": "model", "parts": [{"text": step}]},
                         model=self.model, latency_ms=5)


@pytest.fixture
def engine():
    eng = make_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = Session()
    admin = User(username="admin", full_name="Admin", password_hash=hash_password("admin123"), role="admin")
    owner = User(username="owner", full_name="Chủ", password_hash=hash_password("owner123"), role="owner")
    staff = User(username="staff", full_name="Nhân viên", password_hash=hash_password("staff123"), role="staff")
    acc = Category(name="Phụ kiện")
    session.add_all([admin, owner, staff, acc])
    session.flush()
    session.add_all([
        Product(code="PK001", name="Tai nghe Bluetooth A1", category_id=acc.id, sale_price=350_000,
                cost_price=220_000, stock=12, description="Pin 20 giờ"),
        Product(code="PK002", name="Tai nghe Bluetooth A2 Pro", category_id=acc.id, sale_price=490_000,
                cost_price=310_000, stock=0, description="Pin 30 giờ, chống ồn"),
        Product(code="PK003", name="Sạc nhanh 20W", category_id=acc.id, sale_price=190_000,
                cost_price=95_000, stock=50, description="Sạc nhanh PD"),
        Customer(code="KH0001", name="Phạm Minh Anh", phone="0901234567", group="vip"),
    ])
    session.commit()
    yield session
    session.close()


@pytest.fixture
def fake_ai():
    return FakeAI()


@pytest.fixture
def client(engine, db, fake_ai):
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_ai_client] = lambda: fake_ai
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def owner_h(client):
    return _login(client, "owner", "owner123")


@pytest.fixture
def staff_h(client):
    return _login(client, "staff", "staff123")


@pytest.fixture
def admin_h(client):
    return _login(client, "admin", "admin123")
