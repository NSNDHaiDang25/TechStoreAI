"""Mẫu in khổ 80 mm (SRS 8.6, FR-PAY-07, 08, 09): hóa đơn bán hàng, phiếu đổi trả, biên nhận bảo hành.

Dùng fpdf2 với font DejaVu kèm trong mã nguồn nên in được tiếng Việt có dấu trên mọi máy.
Trang dài theo nội dung: vẽ thử một lần để đo chiều cao rồi vẽ lại trên trang đúng kích thước.
"""
from collections.abc import Callable

from fpdf import FPDF

from app.services.export import FONT_DIR, vnd

WIDTH = 80
MARGIN = 4


class Receipt:
    def __init__(self, store: dict):
        self.store = store
        self.ops: list[Callable[[FPDF], None]] = []

    # -- các lệnh vẽ, ghi lại để vẽ hai lần
    def text(self, value: str, size: float = 8, bold: bool = False, align: str = "L") -> "Receipt":
        def op(pdf: FPDF):
            pdf.set_font("D", "B" if bold else "", size)
            pdf.multi_cell(0, size * 0.48, value, align=align, new_x="LMARGIN", new_y="NEXT")
        self.ops.append(op)
        return self

    def pair(self, left: str, right: str, size: float = 8, bold: bool = False) -> "Receipt":
        def op(pdf: FPDF):
            pdf.set_font("D", "B" if bold else "", size)
            y = pdf.get_y()
            w = pdf.w - 2 * MARGIN
            right_w = pdf.get_string_width(right) + 1
            pdf.multi_cell(w - right_w - 1, size * 0.48, left, new_x="LMARGIN", new_y="NEXT")
            end_y = pdf.get_y()
            pdf.set_xy(pdf.w - MARGIN - right_w, y)
            pdf.cell(right_w, size * 0.48, right, align="R")
            pdf.set_xy(MARGIN, max(end_y, y + size * 0.48))
        self.ops.append(op)
        return self

    def rule(self) -> "Receipt":
        def op(pdf: FPDF):
            pdf.ln(1)
            pdf.set_dash_pattern(dash=0.8, gap=0.6)
            pdf.line(MARGIN, pdf.get_y(), pdf.w - MARGIN, pdf.get_y())
            pdf.set_dash_pattern()
            pdf.ln(1.5)
        self.ops.append(op)
        return self

    def space(self, mm: float = 2) -> "Receipt":
        self.ops.append(lambda pdf: pdf.ln(mm))
        return self

    def header(self, title: str, code: str, when: str, reprint: bool = False) -> "Receipt":
        s = self.store
        self.text(s.get("store_name") or "TechStoreAI", 11, True, "C")
        for line in (s.get("store_address"), s.get("store_phone") and f"ĐT: {s['store_phone']}",
                     s.get("store_tax_code") and f"MST: {s['store_tax_code']}"):
            if line:
                self.text(line, 7, align="C")
        self.space(1).text(title, 10, True, "C")
        if reprint:
            self.text("BẢN IN LẠI", 8, True, "C")
        self.text(f"Số: {code}", 8, align="C").text(when, 7, align="C").rule()
        return self

    def _render(self, height: float) -> FPDF:
        pdf = FPDF(unit="mm", format=(WIDTH, height))
        pdf.set_margins(MARGIN, MARGIN, MARGIN)
        pdf.set_auto_page_break(False)
        pdf.add_font("D", "", str(FONT_DIR / "DejaVuSans.ttf"))
        pdf.add_font("D", "B", str(FONT_DIR / "DejaVuSans-Bold.ttf"))
        pdf.add_page()
        for op in self.ops:
            op(pdf)
        return pdf

    def output(self) -> bytes:
        probe = self._render(2000)
        return bytes(self._render(max(60, probe.get_y() + MARGIN + 2)).output())


PAY_VI = {"cash": "Tiền mặt", "bank_transfer": "Chuyển khoản", "card": "Thẻ (POS)"}


def invoice_pdf(inv, store: dict, warranties: dict[int, object], reprint: bool = False) -> bytes:
    r = Receipt(store).header("HÓA ĐƠN BÁN HÀNG", inv.code, f"{inv.created_at:%d/%m/%Y %H:%M}", reprint)
    r.text(f"Thu ngân: {inv.user.full_name}", 7)
    if inv.customer:
        r.text(f"Khách: {inv.customer.name}" + (f" - {inv.customer.phone}" if inv.customer.phone else ""), 7)
    r.rule()
    for it in inv.items:
        r.text(it.product.name, 8, True)
        r.pair(f"  {it.quantity} x {vnd(it.unit_price)}", vnd(it.line_total))
        if it.discount_amount:
            r.pair("  Giảm giá", f"-{vnd(it.discount_amount)}", 7)
        w = warranties.get(it.id)
        if it.serial is not None:
            r.text(f"  Serial/IMEI: {it.serial.serial_no}", 7)
        if w is not None:
            r.text(f"  Bảo hành đến: {w.end_date:%d/%m/%Y}", 7)  # FR-PAY-08
    r.rule()
    r.pair("Tạm tính", vnd(inv.subtotal))
    if inv.promo_discount:
        r.pair("Khuyến mãi" + (f" ({inv.promotion.code or inv.promotion.name})" if inv.promotion else ""),
               f"-{vnd(inv.promo_discount)}")
    if inv.points_discount:
        r.pair(f"Dùng {inv.points_used} điểm", f"-{vnd(inv.points_discount)}")
    r.pair("TỔNG THANH TOÁN", vnd(inv.total), 10, True)
    r.pair("Trong đó VAT", vnd(inv.vat_amount), 7)
    r.pair("Thanh toán", PAY_VI.get(inv.payment_method, inv.payment_method), 7)
    if inv.cash_received is not None:
        r.pair("Tiền khách đưa", vnd(inv.cash_received), 7).pair("Tiền thừa", vnd(inv.cash_received - inv.total), 7)
    if inv.payment_ref and inv.payment_method != "cash":
        r.pair("Mã giao dịch", inv.payment_ref, 7)
    if inv.customer and inv.points_earned:
        r.pair("Điểm cộng", str(inv.points_earned), 7)
    if inv.status == "pending_payment":
        r.text("CHƯA THANH TOÁN - chờ chuyển khoản", 8, True, "C")
    elif inv.status == "cancelled":
        r.text("HÓA ĐƠN ĐÃ HỦY", 9, True, "C")
    r.rule().text("Đổi trả trong 24 giờ kèm hóa đơn. Cảm ơn quý khách!", 7, align="C")
    return r.output()


def return_pdf(ret, store: dict) -> bytes:
    r = Receipt(store).header("PHIẾU ĐỔI TRẢ", ret.code, f"{ret.created_at:%d/%m/%Y %H:%M}")
    r.text(f"Hóa đơn gốc: {ret.invoice.code}", 7).text(f"Người xử lý: {ret.user.full_name}", 7)
    r.text(f"Lý do: {ret.reason}", 7).rule()
    for ri in ret.items:
        it = ri.invoice_item
        r.text(it.product.name, 8, True)
        r.pair(f"  Trả {ri.quantity} ({'nhập lại kho' if ri.restock else 'hàng lỗi'})", vnd(ri.refund_amount))
        if it.serial is not None:
            r.text(f"  Serial/IMEI: {it.serial.serial_no}", 7)
    r.rule().pair("TIỀN HOÀN", vnd(ret.refund_amount), 10, True)
    r.pair("Hoàn qua", PAY_VI.get(ret.invoice.payment_method, ret.invoice.payment_method), 7)
    if ret.points_reversed:
        r.pair("Điểm bị trừ", str(ret.points_reversed), 7)
    if ret.new_invoice is not None:
        diff = ret.new_invoice.total - ret.refund_amount
        r.pair("Hóa đơn đổi mới", ret.new_invoice.code, 7)
        r.pair("Khách trả thêm" if diff >= 0 else "Trả lại khách", vnd(abs(diff)), 8, True)
    r.space(6).pair("Khách hàng ký", "Nhân viên ký", 7)
    return r.output()


TICKET_VI = {"received": "Đã tiếp nhận", "in_repair": "Đang sửa", "waiting_parts": "Chờ linh kiện",
             "done": "Đã sửa xong", "rejected": "Từ chối bảo hành", "returned": "Đã trả khách"}


def warranty_ticket_pdf(t, store: dict) -> bytes:
    w = t.warranty
    r = Receipt(store).header("BIÊN NHẬN BẢO HÀNH", t.code, f"{t.received_at:%d/%m/%Y %H:%M}")
    r.text(f"Sản phẩm: {w.product.name}", 8, True)
    if w.serial is not None:
        r.text(f"Serial/IMEI: {w.serial.serial_no}", 7)
    r.text(f"Hóa đơn: {w.invoice_item.invoice.code}", 7)
    r.text(f"Bảo hành: {w.start_date:%d/%m/%Y} - {w.end_date:%d/%m/%Y}", 7)
    if w.customer:
        r.text(f"Khách: {w.customer.name}" + (f" - {w.customer.phone}" if w.customer.phone else ""), 7)
    r.rule().text("Mô tả lỗi:", 8, True).text(t.issue_description, 8)
    r.pair("Trạng thái", TICKET_VI.get(t.status, t.status), 8, True)
    if t.resolution:
        r.text("Kết quả xử lý:", 8, True).text(t.resolution, 8)
    r.text(f"Người tiếp nhận: {t.user.full_name}", 7)
    r.rule().text("Vui lòng mang biên nhận khi nhận lại máy.", 7, align="C")
    r.space(6).pair("Khách hàng ký", "Nhân viên ký", 7)
    return r.output()
