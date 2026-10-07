# Minh chứng sử dụng AI trong SDLC

Tài liệu này ghi lại **vai trò thứ nhất của AI: công cụ hỗ trợ phát triển phần mềm** qua từng giai đoạn. (Vai trò thứ hai là *AI là thành phần của sản phẩm*: chatbot, báo cáo, hỏi đáp, xem `01_phan_tich_thiet_ke.md` mục 10.)

> **Hướng dẫn cho nhóm:** mỗi lần dùng AI, hãy thêm một mục theo mẫu ở cuối file: prompt đã dùng, tóm tắt phản hồi, **phần nhóm đã sửa/kiểm chứng**. Có thể chụp màn hình hội thoại, lưu vào `docs/evidence/` và dẫn link. Giảng viên đánh giá cao việc ghi rõ *AI sai ở đâu và nhóm phát hiện thế nào*.

## Công cụ AI đã dùng

| Công cụ | Mục đích |
|---|---|
| Claude Code (Anthropic) | Phân tích đề, thiết kế, sinh mã nguồn, test, tài liệu |
| Google Gemini API | AI tích hợp trong sản phẩm |
| *(bổ sung: ChatGPT, Copilot... nếu nhóm có dùng)* | |

---

## Giai đoạn 1: Phân tích yêu cầu và thiết kế (KT1)

### #1. Phân tích đề tài, chọn công nghệ

- **Prompt:** dán toàn văn đề tài "Hệ thống quản lý bán hàng có tích hợp AI" và yêu cầu làm cả tài liệu phân tích thiết kế lẫn mã nguồn; chọn AI Engine là Gemini API.
- **Phản hồi AI (tóm tắt):** đề xuất FastAPI + SQLAlchemy + SQLite + SPA HTML/JS thuần (không cần build), 3 vai trò, 9 bảng dữ liệu, tách `prompts/`, chế độ AI dự phòng khi chưa có key.
- **Nhóm kiểm chứng / chỉnh sửa:** *(điền)*

### #2. Actor, use case, yêu cầu chức năng/phi chức năng, ERD, wireframe

- **Kết quả:** `docs/01_phan_tich_thiet_ke.md`, gồm 4 sơ đồ quy trình, sơ đồ use case, 17 FR, 12 NFR, ma trận phân quyền, ERD, kiến trúc và 4 wireframe.
- **Quyết định thiết kế đáng chú ý do AI đề xuất:** lưu tiền dạng số nguyên; lưu `unit_cost` trong chi tiết hóa đơn để lãi gộp kỳ cũ không đổi; bảng `stock_movements` làm nhật ký nhập-xuất-tồn; không dùng text-to-SQL cho hỏi đáp để tránh rủi ro bảo mật.
- **Nhóm kiểm chứng:** *(điền, ví dụ: đối chiếu ERD với mô hình trong `app/models.py`, render sơ đồ trên mermaid.live)*

## Giai đoạn 2: Xây dựng chức năng quản lý (KT2)

### #3. Sinh cấu trúc dự án, model, schema, API CRUD, giao diện

- **Kết quả:** `app/` (models, schemas, routers, services), `static/` (SPA), `scripts/seed.py`.

### #4. Truy vấn doanh thu, tồn kho, sản phẩm bán chạy

- **Kết quả:** `app/services/reports.py`. Nhóm theo ngày/tháng làm ở Python để chạy giống nhau trên SQLite/PostgreSQL/MySQL (hàm `date()` khác nhau giữa các CSDL).

### #5. Debug lỗi cập nhật tồn kho khi hủy / sửa hóa đơn

Các lỗi điển hình AI chỉ ra và cách xử lý trong `app/services/inventory.py`:

| Lỗi tiềm ẩn | Hậu quả | Cách xử lý |
|---|---|---|
| Hủy hóa đơn 2 lần | Tồn kho bị cộng lại 2 lần | Kiểm tra `status == 'cancelled'` → báo lỗi |
| Sửa hóa đơn: trừ kho mới trước khi hoàn kho cũ | Báo thiếu hàng sai (VD: HĐ đang giữ 12/12 cái, sửa thành 12 vẫn lỗi) | Hoàn kho dòng cũ **trước**, rồi mới trừ dòng mới |
| Sửa hóa đơn thất bại giữa chừng | Kho đã hoàn nhưng HĐ mới chưa lưu, kho sai lệch | Cả thao tác trong 1 giao dịch; lỗi → `rollback` |
| Một sản phẩm xuất hiện ở 2 dòng trong HĐ | Kiểm tra tồn từng dòng riêng nên lọt (7 + 6 > 12) | Gộp số lượng theo sản phẩm trước khi kiểm tra |
| Sửa trực tiếp tồn kho trong form sản phẩm | Mất dấu vết, không đối soát được | Bỏ trường `stock` khỏi `ProductUpdate`; dùng "Kiểm kho" có lý do |

Mỗi lỗi có test tương ứng trong `tests/test_inventory.py` và `tests/test_invoices.py`.

## Giai đoạn 3: Tích hợp AI, tối ưu prompt, kiểm thử (KT3)

### #6. Thiết kế prompt tư vấn và prompt báo cáo

- **Kết quả:** `prompts/*.md` (5 file), so sánh 3 phiên bản ở `docs/03_so_sanh_prompt.md`.

### #7. Code gọi API AI: timeout, rate limit, sai định dạng

- **Kết quả:** `app/ai/client.py`: timeout cấu hình được; retry có backoff (1s, 2s, 4s) với 429/5xx/mất mạng; không retry với 400/401/403; trích xuất JSON chịu được code fence; ghi log `logs/ai_calls.jsonl` (không ghi API key).

### #8. Sinh test case

- **Kết quả:** 85 test (`pytest`). Dùng `FakeAI` và `httpx.MockTransport` để test AI không cần mạng.

## Giai đoạn 4: Hoàn thiện, triển khai (Cuối kỳ)

### #9. README, dữ liệu mẫu, kịch bản demo, Docker

- **Kết quả:** `README.md`, `docs/04_kich_ban_demo.md`, `Dockerfile`, `docker-compose.yml`.

### #10. Review bảo mật API key và phân quyền dữ liệu

| Hạng mục | Kết quả kiểm tra |
|---|---|
| API key | Chỉ đọc từ `.env`; `.env` nằm trong `.gitignore` và `.dockerignore`; gửi qua header `x-goog-api-key` (không nằm trong URL nên không lọt vào log truy cập) |
| Mật khẩu | PBKDF2 + salt; so sánh bằng `hmac.compare_digest` |
| Phân quyền | Kiểm tra ở **server** cho mọi endpoint; test `test_staff_cannot_*` |
| Rò rỉ dữ liệu cho AI | Test `test_ai_report_does_not_leak_customer_pii` xác nhận tên/SĐT khách không có trong prompt |
| Nhân viên sửa giá | Server bỏ qua `unit_price` do nhân viên gửi (`test_staff_cannot_override_price`) |
| XSS | Giao diện escape mọi dữ liệu; Markdown từ AI được lọc qua DOMPurify |
| Việc còn lại khi triển khai thật | Đổi `SECRET_KEY`, bật HTTPS, giới hạn tần suất đăng nhập, chuyển sang PostgreSQL |

---

## Mẫu ghi minh chứng (nhóm tự bổ sung)

```markdown
### #N. <Tên công việc>
- Ngày: YYYY-MM-DD · Người thực hiện: ...
- Công cụ: ...
- Prompt:
  > ...
- Phản hồi AI (tóm tắt hoặc ảnh chụp docs/evidence/xxx.png): ...
- AI sai / thiếu ở đâu: ...
- Nhóm đã sửa / kiểm chứng thế nào: ...
```
