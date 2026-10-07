"""Client gọi Gemini API qua REST (httpx): xử lý timeout, hạn mức (429), lỗi 5xx và ghi log.

Nhiều model: gói miễn phí giới hạn số lượt gọi MỖI MODEL mỗi ngày (ví dụ 20 lượt/ngày). Khi model đang dùng
hết lượt (hoặc quá tải, hoặc ngừng hỗ trợ), client tự chuyển sang model kế tiếp trong danh sách dự phòng
và ghi nhớ model đó đang "nghỉ" đến khi hạn mức làm mới, để các câu hỏi sau không gọi lại vô ích.
"""
import json
import logging
import time
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

from app.config import settings

logger = logging.getLogger("ai")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Ngôn ngữ giao diện của người đang hỏi (middleware đọc header Accept-Language). Prompt viết bằng tiếng Việt;
# khi giao diện tiếng Anh thì dặn thêm AI trả lời bằng tiếng Anh, dịch cả tên sản phẩm và nhóm hàng tiếng Việt
# (giữ hãng, model, mã sản phẩm); khóa JSON, SQL và mã giữ nguyên để code còn đọc được.
reply_lang: ContextVar[str] = ContextVar("reply_lang", default="vi")
ENGLISH_NOTE = ("\n\nIMPORTANT: The user interface is in English. Write every natural-language part of your answer in "
                "English, even though these instructions are in Vietnamese. When you mention a product or category "
                "whose name is in Vietnamese, write its English name instead (for example \"Bàn phím cơ Keychron K2\" "
                "-> \"Keychron K2 Mechanical Keyboard\", \"Tai nghe\" -> \"Headphones\"), keeping the brand, model and "
                "product code. Keep JSON keys, SQL statements and product codes exactly as they are.")


def localize(system: str) -> str:
    return system + ENGLISH_NOTE if reply_lang.get() == "en" else system


class AIError(Exception):
    """Lỗi khi gọi AI (hết thời gian, bị giới hạn, phản hồi hỏng...)."""

    def __init__(self, message: str, kind: str = "error"):
        super().__init__(message)
        self.kind = kind  # timeout | rate_limit | quota_day | config | bad_response | error


def next_quota_reset(now: float | None = None) -> datetime:
    """Thời điểm hạn mức ngày của Gemini làm mới: 0 giờ theo giờ Thái Bình Dương (có giờ mùa hè).

    Tự tính giờ mùa hè Mỹ (Chủ nhật thứ 2 tháng 3 đến Chủ nhật đầu tháng 11) để không cần gói tzdata trên Windows.
    Trả về datetime theo UTC.
    """
    utc = datetime.fromtimestamp(time.time() if now is None else now, timezone.utc)

    def offset(d: datetime) -> int:
        mar8 = datetime(d.year, 3, 8, 10, tzinfo=timezone.utc)   # 2:00 PST = 10:00 UTC
        nov1 = datetime(d.year, 11, 1, 9, tzinfo=timezone.utc)   # 2:00 PDT = 09:00 UTC
        dst_start = mar8 + timedelta(days=(6 - mar8.weekday()) % 7)
        dst_end = nov1 + timedelta(days=(6 - nov1.weekday()) % 7)
        return -7 if dst_start <= d < dst_end else -8

    off = offset(utc)
    local = utc + timedelta(hours=off)
    next_midnight = datetime(local.year, local.month, local.day, tzinfo=timezone.utc) + timedelta(days=1)
    return next_midnight - timedelta(hours=off)


def _local_time(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M ngày %d/%m")


@dataclass
class AIResult:
    text: str
    model: str
    latency_ms: int
    retries: int = 0  # số lần gọi thất bại trước khi có phản hồi (timeout, 429, 5xx...), ghi vào ai_logs.retry_count


@dataclass
class ChatReply:
    """Một lượt phản hồi khi dùng function calling: AI trả lời bằng văn bản HOẶC yêu cầu gọi công cụ."""
    text: str
    calls: list[dict]  # [{"name": "search_products", "args": {...}}]
    content: dict      # nội dung gốc của model, gửi lại nguyên vẹn ở lượt sau (giữ cả thoughtSignature)
    model: str
    latency_ms: int


class GeminiClient:
    def __init__(self, api_key: str | None = None, model: str | None = None,
                 timeout: float | None = None, max_retries: int | None = None,
                 transport: httpx.BaseTransport | None = None, fallback_models: list[str] | None = None,
                 clock=time.time, thinking_level: str | None = None):
        self.api_key = api_key if api_key is not None else settings.GEMINI_API_KEY
        self.model = model or settings.GEMINI_MODEL
        fallbacks = settings.GEMINI_FALLBACK_MODELS if fallback_models is None else fallback_models
        self.models = list(dict.fromkeys([self.model, *fallbacks]))  # model chính trước, bỏ trùng
        self.timeout = timeout or settings.AI_TIMEOUT_SECONDS
        self.max_retries = settings.AI_MAX_RETRIES if max_retries is None else max_retries
        self.thinking_level = settings.AI_THINKING_LEVEL if thinking_level is None else thinking_level
        self._transport = transport
        self._clock = clock
        # model -> (thời điểm dùng lại được, lý do: day | minute | busy | gone)
        self._resting: dict[str, tuple[float, str]] = {}
        self._no_thinking: set[str] = set()  # model từ chối tùy chọn mức suy nghĩ: gửi không kèm tùy chọn này

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def available_models(self) -> list[str]:
        now = self._clock()
        return [m for m in self.models if self._resting.get(m, (0, ""))[0] <= now]

    def has_available_model(self) -> bool:
        return bool(self.available_models())

    def status(self) -> dict:
        """Tình trạng từng model: dùng được, hay đang nghỉ (lý do, đến lúc nào)."""
        now = self._clock()
        models = []
        for m in self.models:
            until, reason = self._resting.get(m, (0, None))
            resting = until > now
            models.append({"model": m, "available": not resting, "reason": reason if resting else None,
                           "until": _local_time(until) if resting and until != float("inf") else None})
        return {"active_model": next((x["model"] for x in models if x["available"]), None), "models": models}

    def _rest(self, model: str, seconds: float | None, reason: str) -> None:
        until = float("inf") if seconds is None else self._clock() + seconds
        self._resting[model] = (until, reason)

    def generate(self, system: str, user: str, *, json_mode: bool = False,
                 temperature: float = 0.3, feature: str = "unknown") -> AIResult:
        body = {
            "systemInstruction": {"parts": [{"text": localize(system)}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": 2048},
        }
        if json_mode:
            body["generationConfig"]["responseMimeType"] = "application/json"
        data, latency, model, retries = self._post(body, feature, user)
        text = self._extract_text(data)
        self._log(feature, "ok", latency, user, text, model)
        return AIResult(text=text, model=model, latency_ms=latency, retries=retries)

    def chat(self, system: str, contents: list[dict], *, tools: list[dict], temperature: float = 0.3,
             force_text: bool = False, feature: str = "unknown", model: str | None = None) -> ChatReply:
        """Hội thoại nhiều lượt có khai báo công cụ (Gemini function calling).

        force_text=True: cấm gọi thêm công cụ, buộc AI trả lời bằng văn bản (dùng ở vòng cuối).
        model: ghim model cho các vòng sau của cùng một câu hỏi (chữ ký suy luận chỉ hợp lệ với model đã tạo ra nó).
        """
        body = {
            "systemInstruction": {"parts": [{"text": localize(system)}]},
            "contents": contents,
            "tools": [{"functionDeclarations": tools}],
            "toolConfig": {"functionCallingConfig": {"mode": "NONE" if force_text else "AUTO"}},
            "generationConfig": {"temperature": temperature, "maxOutputTokens": 4096},
        }
        preview = next((p.get("text", "") for c in reversed(contents) if c.get("role") == "user"
                        for p in c.get("parts", []) if "text" in p), "")
        data, latency, used, _ = self._post(body, feature, preview, only=model)
        try:
            candidate = data["candidates"][0]
            content = candidate.get("content") or {}
            parts = content.get("parts") or []
            calls = [{"name": p["functionCall"]["name"], "args": p["functionCall"].get("args") or {},
                      **({"id": p["functionCall"]["id"]} if p["functionCall"].get("id") else {})}
                     for p in parts if "functionCall" in p]
            text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
        except (KeyError, IndexError, TypeError, AttributeError):
            raise AIError("Phản hồi AI sai định dạng", "bad_response")
        if not calls and not text:
            reason = candidate.get("finishReason", "UNKNOWN")
            raise AIError(f"AI không trả về nội dung (finishReason={reason})", "bad_response")
        self._log(feature, "ok", latency, preview, text or json.dumps(calls, ensure_ascii=False), used)
        return ChatReply(text=text, calls=calls, content={"role": "model", "parts": parts},
                         model=used, latency_ms=latency)

    def _post(self, body: dict, feature: str, preview: str, only: str | None = None) -> tuple[dict, int, str, int]:
        """Gửi request lần lượt tới các model còn lượt.
        Trả về (JSON phản hồi, độ trễ ms, model đã trả lời, số lần gọi thất bại trước đó).

        - 429 hết lượt trong ngày: model nghỉ đến khi hạn mức làm mới, chuyển model kế tiếp (không thử lại).
        - 429 theo phút: model nghỉ đúng số giây Google yêu cầu, chuyển model kế tiếp.
        - Timeout / 503 (Google báo quá tải): nghỉ 60 giây và chuyển model NGAY, vì thử lại lúc quá tải
          thường chỉ tốn thêm vài chục giây chờ.
        - 5xx khác, lỗi mạng: thử lại cùng model (backoff), vẫn lỗi thì nghỉ 60 giây và chuyển model.
        - 404 (model ngừng hỗ trợ): bỏ model đó. 400/401/403: lỗi cấu hình (key sai...), dừng ngay.
        """
        if not self.enabled:
            raise AIError("Chưa cấu hình GEMINI_API_KEY", "config")
        candidates = [only] if only else self.available_models()
        if not candidates:
            raise self._all_resting_error()
        headers = {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}
        started = time.perf_counter()
        last_error: AIError | None = None
        failures = 0

        for model in candidates:
            url = GEMINI_URL.format(model=model)
            for attempt in range(self.max_retries + 1):
                try:
                    resp = self._send(url, headers, self._payload(body, model))
                    if (resp.status_code == 400 and self.thinking_level and model not in self._no_thinking
                            and "thinking" in self._error_message(resp).lower()):
                        # Model không hỗ trợ tùy chọn mức suy nghĩ: gửi lại không kèm, ghi nhớ cho các lần sau
                        self._no_thinking.add(model)
                        resp = self._send(url, headers, self._payload(body, model))
                except httpx.TimeoutException:
                    last_error = AIError("AI phản hồi quá lâu (timeout)", "timeout")
                    failures += 1
                    self._busy(model, last_error, feature, preview, started)
                    break
                except httpx.HTTPError as e:
                    last_error = AIError(f"Không kết nối được AI: {e.__class__.__name__}", "error")
                    failures += 1
                else:
                    if resp.status_code == 200:
                        try:
                            data = resp.json()
                        except ValueError:
                            raise AIError("Phản hồi AI sai định dạng", "bad_response")
                        return data, int((time.perf_counter() - started) * 1000), model, failures
                    if resp.status_code == 429:
                        last_error = self._on_quota(model, resp)
                        failures += 1
                        self._log(feature, last_error.kind, 0, preview, str(last_error), model)
                        break  # thử lại cùng model chỉ tốn thêm lượt: chuyển model
                    if resp.status_code == 404:
                        self._rest(model, None, "gone")
                        last_error = AIError(f"Model {model} không còn dùng được: {self._error_message(resp)}", "config")
                        failures += 1
                        self._log(feature, "fail", 0, preview, str(last_error), model)
                        break
                    if resp.status_code < 500:
                        # 400/401/403: key sai, request sai... đổi model cũng vô ích
                        msg = self._error_message(resp)
                        self._log(feature, "fail", 0, preview, msg, model)
                        if resp.status_code in (401, 403):
                            # Thông báo gốc của Google ("Expected OAuth 2 access token...") dễ bị hiểu nhầm là lỗi đăng nhập app
                            raise AIError(f"Google từ chối GEMINI_API_KEY ({resp.status_code}): key sai, đã bị xóa hoặc hết hạn. "
                                          "Tạo key mới tại aistudio.google.com/apikey rồi điền vào .env (chạy trên máy) "
                                          "hoặc mục Environment (trên Render)", "config")
                        raise AIError(f"AI từ chối yêu cầu ({resp.status_code}): {msg}", "config")
                    if resp.status_code == 503:
                        last_error = AIError(f"Model {model} đang quá tải", "error")
                        failures += 1
                        self._busy(model, last_error, feature, preview, started)
                        break
                    last_error = AIError(f"Máy chủ AI lỗi {resp.status_code}", "error")
                    failures += 1
                if attempt < self.max_retries:
                    time.sleep(min(2 ** attempt, 8))  # backoff 1s, 2s, 4s...
            else:
                # hết lượt thử vì lỗi mạng / 5xx: cho model nghỉ một lúc, chuyển model kế tiếp
                self._busy(model, last_error, feature, preview, started)

        if only is None and not self.available_models() and last_error and last_error.kind in ("rate_limit", "quota_day"):
            raise self._all_resting_error()
        raise last_error

    def _send(self, url: str, headers: dict, payload: dict) -> httpx.Response:
        with httpx.Client(timeout=self.timeout, transport=self._transport) as http:
            return http.post(url, headers=headers, json=payload)

    def _payload(self, body: dict, model: str) -> dict:
        """Gắn mức suy nghĩ vào request, trừ model đã từ chối tùy chọn này."""
        if not self.thinking_level or model in self._no_thinking:
            return body
        config = {**body.get("generationConfig", {}), "thinkingConfig": {"thinkingLevel": self.thinking_level}}
        return {**body, "generationConfig": config}

    def _busy(self, model: str, error: AIError, feature: str, preview: str, started: float) -> None:
        """Model quá tải / quá chậm: nghỉ 60 giây để câu hỏi này và các câu sau dùng model kế tiếp."""
        self._rest(model, 60, "busy")
        self._log(feature, error.kind, int((time.perf_counter() - started) * 1000), preview, str(error), model)

    def _on_quota(self, model: str, resp: httpx.Response) -> AIError:
        """Đọc chi tiết lỗi 429: hết lượt trong ngày hay chỉ quá nhanh trong phút."""
        per_day, delay = False, 60.0
        try:
            for d in resp.json()["error"].get("details", []):
                for v in d.get("violations", []) or []:
                    per_day = per_day or "PerDay" in (v.get("quotaId") or "")
                if d.get("retryDelay"):
                    delay = float(str(d["retryDelay"]).rstrip("s") or 60)
        except (ValueError, KeyError, TypeError, AttributeError):
            pass
        if per_day:
            reset = next_quota_reset(self._clock()).timestamp()
            self._rest(model, reset - self._clock(), "day")
            return AIError(f"Model {model} đã hết lượt gọi miễn phí hôm nay, làm mới lúc {_local_time(reset)}", "quota_day")
        delay = max(5.0, min(delay, 300.0))
        self._rest(model, delay, "minute")
        return AIError(f"AI đang nhận quá nhiều yêu cầu, thử lại sau khoảng {int(delay)} giây", "rate_limit")

    def _all_resting_error(self) -> AIError:
        """Không còn model nào gọi được: báo thời điểm sớm nhất dùng lại được."""
        now = self._clock()
        resting = [(until, reason) for m, (until, reason) in self._resting.items() if m in self.models and until > now]
        if resting and all(reason == "gone" for _, reason in resting):
            return AIError("Các model Gemini đã cấu hình không còn dùng được, hãy cập nhật GEMINI_MODEL / "
                           "GEMINI_FALLBACK_MODELS trong .env", "config")
        if resting and all(reason in ("day", "gone") for _, reason in resting):
            resting = [(u, r) for u, r in resting if r == "day"]
            return AIError(f"Đã dùng hết lượt gọi AI miễn phí hôm nay của cả {len(self.models)} model; "
                           f"hạn mức làm mới lúc {_local_time(min(u for u, _ in resting))}", "quota_day")
        soonest = min((u for u, _ in resting if u != float("inf")), default=now + 60)
        return AIError(f"AI đang quá tải hoặc bị giới hạn tần suất, thử lại sau khoảng {max(1, int(soonest - now))} giây", "rate_limit")

    @staticmethod
    def _extract_text(data: dict) -> str:
        try:
            candidate = data["candidates"][0]
            parts = candidate.get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts).strip()
        except (ValueError, KeyError, IndexError, TypeError):
            raise AIError("Phản hồi AI sai định dạng", "bad_response")
        if not text:
            reason = candidate.get("finishReason", "UNKNOWN")
            raise AIError(f"AI không trả về nội dung (finishReason={reason})", "bad_response")
        return text

    @staticmethod
    def _error_message(resp: httpx.Response) -> str:
        try:
            return resp.json()["error"]["message"][:200]
        except Exception:
            return resp.text[:200]

    @staticmethod
    def _log(feature: str, status: str, latency_ms: int, prompt: str, output: str, model: str = "") -> None:
        """Ghi nhật ký gọi AI ra logs/ai_calls.jsonl (làm minh chứng và debug). Không ghi API key."""
        try:
            settings.LOG_DIR.mkdir(exist_ok=True)
            record = {
                "time": time.strftime("%Y-%m-%d %H:%M:%S"), "feature": feature, "model": model, "status": status,
                "latency_ms": latency_ms, "prompt_preview": prompt[:500], "output_preview": output[:1000],
            }
            with open(settings.LOG_DIR / "ai_calls.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            logger.warning("Không ghi được log AI")


_client: GeminiClient | None = None


def get_ai_client() -> GeminiClient:
    """Dependency FastAPI; test sẽ override bằng client giả."""
    global _client
    if _client is None:
        _client = GeminiClient()
    return _client
