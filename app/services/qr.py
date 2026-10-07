"""Sinh mã QR dạng SVG: tem QR sản phẩm và mã VietQR thanh toán chuyển khoản.

VietQR theo chuẩn EMVCo (NAPAS): chuỗi các trường TLV (mã 2 số + độ dài 2 số + giá trị),
kết thúc bằng CRC16-CCITT. Mọi app ngân hàng Việt Nam đều quét được, tự điền số tài khoản,
số tiền và nội dung chuyển khoản.
"""
import io
import re
import unicodedata

import qrcode
import qrcode.image.svg

from app.config import settings


def qr_svg(data: str, border: int = 2) -> str:
    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, border=border,
                      error_correction=qrcode.constants.ERROR_CORRECT_M)
    buf = io.BytesIO()
    img.save(buf)
    svg = buf.getvalue().decode("utf-8")
    svg = re.sub(r"<\?xml[^>]*\?>\s*", "", svg)
    # Bỏ kích thước cố định (mm) để SVG co giãn theo khung chứa
    return re.sub(r'\s(width|height)="[^"]*"', "", svg, count=2)


def _tlv(tag: str, value: str) -> str:
    return f"{tag}{len(value):02d}{value}"


def crc16_ccitt(data: str) -> str:
    crc = 0xFFFF
    for byte in data.encode("utf-8"):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
            crc &= 0xFFFF
    return f"{crc:04X}"


def clean_transfer_content(text: str) -> str:
    """Nội dung chuyển khoản: bỏ dấu, chỉ giữ chữ số/chữ cái/khoảng trắng, tối đa 25 ký tự."""
    text = unicodedata.normalize("NFD", text).replace("đ", "d").replace("Đ", "D")
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"[^A-Za-z0-9 ]", "", text)[:25].strip()


def vietqr_payload(bank_bin: str, account_no: str, amount: int | None, content: str | None) -> str:
    merchant = _tlv("00", "A000000727") + _tlv("01", _tlv("00", bank_bin) + _tlv("01", account_no)) \
        + _tlv("02", "QRIBFTTA")
    payload = _tlv("00", "01") + _tlv("01", "12" if amount else "11") + _tlv("38", merchant) + _tlv("53", "704")
    if amount:
        payload += _tlv("54", str(int(amount)))
    payload += _tlv("58", "VN")
    if content:
        payload += _tlv("62", _tlv("08", clean_transfer_content(content)))
    payload += "6304"
    return payload + crc16_ccitt(payload)


def vietqr(amount: int, content: str) -> dict:
    payload = vietqr_payload(settings.VIETQR_BANK_BIN, settings.VIETQR_ACCOUNT_NO, amount, content)
    return {
        "svg": qr_svg(payload), "payload": payload, "amount": amount,
        "content": clean_transfer_content(content),
        "bank_name": settings.VIETQR_BANK_NAME, "account_no": settings.VIETQR_ACCOUNT_NO,
        "account_name": settings.VIETQR_ACCOUNT_NAME,
        "is_demo": settings.VIETQR_ACCOUNT_NO == "0123456789",
    }
