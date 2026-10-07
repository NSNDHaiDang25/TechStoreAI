# Kịch bản demo (khoảng 10 phút)

**Chuẩn bị:** `python -m scripts.seed` (dữ liệu sạch) → `uvicorn app.main:app` → mở http://localhost:8000. Nên có `GEMINI_API_KEY` để demo AI thật; nếu mạng lỗi, hệ thống tự chuyển chế độ dự phòng (badge "AI: chế độ dự phòng").

## Phần 1: Nhân viên bán hàng (3 phút)

1. Đăng nhập bằng nút **Nhân viên** (staff/staff123). Menu chỉ có: Bán hàng, Hóa đơn, Khách hàng, Sản phẩm, Chatbot. *→ Minh họa phân quyền.*
2. **Chatbot tư vấn** → bấm gợi ý *"Khách cần tai nghe dưới 500000 đồng, pin lâu, còn hàng"*.
   - AI gợi ý các sản phẩm còn hàng, kèm giá và tồn.
   - Nhấn mạnh: *Tai nghe A2 Pro (PK002) khớp nhu cầu nhất nhưng đang hết hàng nên không được gợi ý.*
   - Bấm **+ Giỏ hàng** trên một sản phẩm.
3. **Bán hàng** → sản phẩm đã có trong giỏ. Thêm *Sạc nhanh 20W*.
   - Gõ `PK005` vào ô tìm kiếm rồi Enter (giống máy quét mã vạch USB) → sản phẩm vào thẳng giỏ.
   - Bấm **Quét QR** → đưa tem QR (in từ trang Sản phẩm → *In tem QR*, hoặc mở tem trên điện thoại) vào camera → nghe tiếng bíp, sản phẩm vào giỏ.
   - Ô khách hàng gõ "0901" → chọn *Phạm Minh Anh (VIP)*.
   - Giảm giá **5 %**, chọn **Tiền mặt**, bấm gợi ý mệnh giá → hệ thống tính tiền thừa → **Thanh toán** → hóa đơn in ra có dòng *Khách đưa / Tiền thừa*.
   - Lập thêm 1 hóa đơn chọn **Quét mã QR** → mã VietQR hiện số tiền; dùng app ngân hàng trên điện thoại quét thử để thấy số tài khoản, số tiền, nội dung được điền sẵn (**không bấm chuyển**) → bấm *Đã nhận tiền, hoàn tất*.
4. Thử bấm vào sản phẩm *Hết hàng* (mờ, không bấm được). Tăng số lượng quá tồn kho → báo lỗi.
5. **Sản phẩm** → cột giá nhập bị ẩn với nhân viên.

## Phần 2: Chủ cửa hàng (5 phút)

1. Đăng xuất → **Chủ cửa hàng** (owner/owner123) → **Tổng quan**: doanh thu hôm nay (có hóa đơn vừa lập), biểu đồ 30 ngày, top 5, cảnh báo sắp hết hàng.
2. **Hóa đơn** → mở hóa đơn vừa lập → **Hủy hóa đơn** (lý do "Khách đổi ý") → vào **Nhập - xuất - tồn** thấy dòng *Hủy hóa đơn* `+1`. *→ Minh họa hoàn tồn kho.*
3. **Nhập hàng** → **Tạo phiếu nhập**: chọn *Tai nghe Bluetooth A2 Pro*, SL 10 → Lưu → sản phẩm hết hàng đã có hàng lại.
4. **Báo cáo doanh thu** → chọn *Tháng trước* → xem KPI, biểu đồ theo ngày/nhóm hàng, bán chạy/bán chậm → xuất **PDF** và **Excel**.
5. **Báo cáo AI** → *30 ngày* → AI viết báo cáo 5 mục, có khuyến nghị nhập hàng → **Tải .md**.
6. **Hỏi đáp dữ liệu** → *"Tháng này mặt hàng nào bán chậm?"* → rồi tự gõ *"Doanh thu tháng 8 so với tháng trước thế nào?"*.

## Phần 3: So sánh prompt và độ bền (2 phút)

1. **Chatbot** → ô **Prompt** chọn **v1** → hỏi *"Khách muốn tai nghe chống ồn tốt nhất"*. Nếu AI nhắc hàng hết, hệ thống hiện cảnh báo vàng *"Đã loại bỏ gợi ý không hợp lệ hoặc hết hàng"*. Chuyển sang **v3** và hỏi lại để so sánh.
2. (Tùy chọn) Xóa `GEMINI_API_KEY` trong `.env` và khởi động lại → hệ thống vẫn chạy ở chế độ dự phòng. *→ Minh họa xử lý lỗi AI.*
3. Chạy `pytest -q` → 85 test pass.

## Câu hỏi thường gặp khi bảo vệ

| Câu hỏi | Gợi ý trả lời |
|---|---|
| Làm sao đảm bảo AI không tư vấn hàng hết? | 3 lớp: lọc trước dữ liệu, JSON có cấu trúc, hậu kiểm bằng code (xem `docs/03_so_sanh_prompt.md`) |
| Để AI tự viết SQL có an toàn không? | Có 5 lớp (SRS bảng 6.6): chỉ chủ cửa hàng dùng; AI chỉ biết 7 view `v_ai_*` đã bỏ cột nhạy cảm; bộ kiểm tra SQL bằng code; kết nối SQLite chỉ đọc (`mode=ro`, `query_only`); LIMIT 200 và timeout 5 giây. Demo: hỏi "mật khẩu admin là gì" để thấy SQL bị chặn và ghi `rejected_sql` trong Nhật ký AI |
| Hủy/sửa hóa đơn thì tồn kho xử lý thế nào? | Hoàn dòng cũ rồi trừ dòng mới trong 1 giao dịch; lỗi thì rollback; có nhật ký `stock_movements` |
| Gửi gì cho AI, có lộ thông tin khách không? | Chỉ số liệu tổng hợp/sản phẩm; không gửi tên, SĐT, thanh toán; có test kiểm chứng |
| AI lỗi / hết quota thì sao? | Timeout, retry với 429/5xx, rồi chuyển chế độ dự phòng rule-based; giao diện hiện nhãn "Dự phòng" |
