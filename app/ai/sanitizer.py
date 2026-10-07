"""Lọc dữ liệu nhạy cảm khỏi mọi nội dung gửi cho AI (SRS FR-AIG-03, BR-42, bảng 6.9).

- Số điện thoại (0912345678, 0912 345 678, +84 912 345 678)  -> [SĐT]
- Email (nam.tran@example.com)                                -> [EMAIL]
- Dãy 9 đến 19 chữ số liền (số tài khoản, số thẻ, mã giao dịch) -> [SỐ]

Áp dụng cho cả câu hỏi người dùng nhập (nhân viên có thể dán nguyên số điện thoại của khách vào ô chat)
và lịch sử hội thoại. Câu hỏi sau khi lọc là bản được lưu vào ai_logs.
"""
import re

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Di động / cố định Việt Nam: 0 hoặc +84 / 84, tiếp theo 9 chữ số, cho phép dấu cách, chấm, gạch giữa các cụm
_PHONE = re.compile(r"(?<![\w.])(?:\+?84[\s.\-]?|0)(?:\d[\s.\-]?){8}\d(?![\w])")
_LONG_NUMBER = re.compile(r"(?<!\d)\d{9,19}(?!\d)")

PHONE_TAG, EMAIL_TAG, NUMBER_TAG = "[SĐT]", "[EMAIL]", "[SỐ]"


def scrub(text: str | None) -> str:
    """Thay số điện thoại, email, dãy số dài bằng nhãn. Không đổi các phần còn lại của câu."""
    if not text:
        return ""
    text = _EMAIL.sub(EMAIL_TAG, text)
    text = _PHONE.sub(PHONE_TAG, text)
    return _LONG_NUMBER.sub(NUMBER_TAG, text)


def scrub_history(history: list[dict] | None) -> list[dict]:
    return [{**turn, "content": scrub(str(turn.get("content", "")))} for turn in (history or [])]
