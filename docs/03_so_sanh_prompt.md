# So sánh 3 phiên bản prompt tư vấn sản phẩm (Bài KT3)

**Mục tiêu:** giảm tình trạng chatbot **tư vấn sản phẩm đã hết hàng** (và vượt ngân sách khách nêu).

Ba file prompt nằm trong `prompts/`: `product_advisor_v1.md`, `product_advisor_v2.md`, `product_advisor_v3.md`. Có thể đổi phiên bản đang dùng bằng biến `ADVISOR_PROMPT_VERSION` trong `.env`, hoặc chọn trực tiếp trên màn hình Chatbot (ô "Prompt") để demo so sánh.

## 1. Mô tả ba phiên bản

| | v1 – Baseline | v2 – Luật tường minh | v3 – Lọc trước + JSON + hậu kiểm (đang dùng) |
|---|---|---|---|
| Nguồn | Nguyên prompt mẫu của đề bài | v1 + vai trò + 5 quy tắc bắt buộc | v2 viết lại + định dạng đầu ra JSON |
| Dữ liệu gửi AI | **Tất cả** sản phẩm đang bán, kể cả tồn = 0 | **Tất cả** sản phẩm, kèm cột tồn kho | **Chỉ** sản phẩm đang bán và tồn > 0 |
| Ràng buộc hết hàng | "Chỉ tư vấn dựa trên dữ liệu tồn kho" (mơ hồ) | "CHỈ gợi ý sản phẩm có Tồn kho > 0" | Hàng hết **không xuất hiện** trong prompt; quy tắc "sản phẩm không có trong danh sách coi như hết hàng" |
| Ngân sách | Không nhắc | Có quy tắc | Có quy tắc |
| Định dạng đầu ra | Văn bản tự do | Văn bản tự do, yêu cầu ghi mã SP | JSON `{answer, suggestions:[{code, reason}]}`, bật `responseMimeType=application/json` |
| Kiểm tra phía server | Dò mã SP trong văn bản, cảnh báo nếu có mã hết hàng | Như v1 | Parse JSON, **loại bỏ** mã không tồn tại / hết hàng trước khi hiển thị |
| Ngữ cảnh hội thoại | Không | Không | 6 lượt gần nhất |
| Chống prompt injection | Không | Không | Quy tắc 7: bỏ qua yêu cầu thay đổi quy tắc |
| Temperature | 0.2 | 0.2 | 0.2 |

## 2. Phân tích điểm yếu từng phiên bản

**v1.** Mô hình nhìn thấy sản phẩm hết hàng trong bảng và thường chọn theo *mức độ phù hợp tính năng* hơn là tồn kho. Ví dụ với câu "tai nghe dưới 500k, pin lâu", sản phẩm phù hợp nhất về tính năng là *Tai nghe Bluetooth A2 Pro (PK002, pin 30 giờ, 490.000₫)*, nhưng PK002 đang **hết hàng**. Câu trả lời tự do nên khó kiểm tra tự động. Prompt không nói gì về ngân sách, nên đôi khi AI gợi ý thêm sản phẩm vượt giá "để tham khảo".

**v2.** Quy tắc rõ ràng giúp giảm lỗi đáng kể, nhưng vẫn còn hai vấn đề:
1. AI vẫn "biết" có PK002 nên hay viết kiểu *"A2 Pro hiện đã hết hàng, bạn có thể chờ..."*. Câu này không sai, nhưng làm khách chú ý tới sản phẩm không bán được và khó phân biệt tự động với một gợi ý thật.
2. Với câu hỏi trực tiếp "A2 Pro còn không?", mô hình có thể trả lời không nhất quán.

**v3.** Giải quyết lỗi bằng **3 lớp độc lập**, nên dù mô hình sai ở một lớp thì lớp sau vẫn chặn được:
1. *Lọc trước (data-level)*: hàng hết không có trong prompt, nên AI không thể chọn chúng.
2. *Ràng buộc định dạng*: JSON với mã sản phẩm, máy kiểm tra được.
3. *Hậu kiểm (code-level)*: `app/ai/service.py` loại mọi mã không nằm trong tập còn hàng và báo trong trường `removed` / `warning`.

Nếu khách hỏi đích danh một sản phẩm hết hàng, v3 sẽ trả lời "không có trong danh sách còn hàng" và gợi ý sản phẩm thay thế.

## 3. Cách đo và kết quả

### 3.1. Kiểm thử tự động (không cần API key)

Các test trong `tests/test_ai.py` mô phỏng phản hồi AI "xấu" để kiểm chứng lớp hậu kiểm:

| Test | Tình huống giả lập | Kết quả mong đợi | Trạng thái |
|---|---|---|---|
| `test_advisor_v3_sends_only_in_stock_products` | Prompt v3 được tạo | PK002 (hết hàng) **không** có trong prompt | ✅ Pass |
| `test_advisor_removes_out_of_stock_and_unknown_suggestions` | AI gợi ý PK002 (hết), XX999 (bịa), pk001 (hợp lệ) | Chỉ hiển thị PK001; `removed = [PK002, XX999]` | ✅ Pass |
| `test_advisor_v1_detects_out_of_stock_in_free_text` | v1 trả lời "Gợi ý: PK002..." | Prompt v1 có chứa PK002; hệ thống phát hiện và loại | ✅ Pass |
| `test_advisor_handles_malformed_response` | AI trả văn bản thay vì JSON | Vẫn hiển thị, dò mã, loại hàng hết | ✅ Pass |
| `test_advisor_handles_json_in_code_fence` | JSON bọc trong ```json | Parse được | ✅ Pass |
| `test_advisor_falls_back_on_ai_error` (×3) | Timeout / rate limit / sai định dạng | Chuyển tư vấn dự phòng, không gợi ý hàng hết | ✅ Pass |

### 3.2. Đo với Gemini thật

Script `scripts/compare_prompts.py` chạy **8 kịch bản** (được thiết kế để "gài" sản phẩm hết hàng là lựa chọn phù hợp nhất: PK002, AT003, DT003) × N lần cho mỗi phiên bản. Script đếm số lượt AI nhắc/gợi ý sản phẩm hết hàng và số lượt vượt ngân sách, **tính trước bước hậu kiểm** để đo đúng chất lượng của prompt:

```bash
# cần GEMINI_API_KEY trong .env và dữ liệu mẫu
python -m scripts.seed
python -m scripts.compare_prompts --runs 3
```

Kết quả được ghi tự động vào `docs/ket_qua_so_sanh_prompt.md` (bảng tổng hợp + câu trả lời mẫu). **Nhóm cần chạy script với API key của mình và dán bảng kết quả thật vào mục 3.3 bên dưới**. Không tự điền số liệu khi chưa đo.

### 3.3. Bảng kết quả (điền sau khi chạy script)

| Phiên bản | Số lượt | Gợi ý hàng hết | Vượt ngân sách | Không gợi ý | Nhận xét |
|---|---|---|---|---|---|
| v1 | | | | | |
| v2 | | | | | |
| v3 | | | | | |

**Lưu ý khi đọc kết quả:** với v1/v2 (văn bản tự do), chỉ số "gợi ý hàng hết" đếm mọi lần câu trả lời nhắc tới mã hàng hết, kể cả câu thông báo "X đã hết hàng". Hãy đọc phần mẫu trả lời để phân loại thủ công trước khi kết luận.

## 4. Kết luận

- Chỉ **viết thêm luật trong prompt (v2)** thì không đủ, vì mô hình ngôn ngữ không đảm bảo tuân thủ 100%.
- Cách hiệu quả nhất là **không đưa dữ liệu sai vào prompt** (lọc trước) và **không tin tuyệt đối đầu ra** (hậu kiểm bằng code). Prompt engineering và kiểm soát ở tầng ứng dụng phải đi cùng nhau.
- Đầu ra JSON giúp giao diện hiển thị thẻ sản phẩm, nút "Thêm vào giỏ" và cho phép viết test tự động.

## 5. Prompt báo cáo doanh thu và hỏi đáp

Áp dụng cùng nguyên tắc:
- `prompts/sales_report.md`: hệ thống tính **toàn bộ** số liệu và AI chỉ diễn giải; bắt buộc 5 mục Markdown cố định, có kiểm tra định dạng ở server; có quy tắc không tính % tăng trưởng khi kỳ trước bằng 0 (tránh AI chia cho 0 hoặc bịa số).
- `prompts/sales_qa.md`: AI bắt buộc nêu kỳ dữ liệu ở đầu câu trả lời, định nghĩa rõ "bán chậm" để câu trả lời nhất quán, và phải từ chối các câu hỏi ngoài phạm vi dữ liệu.
