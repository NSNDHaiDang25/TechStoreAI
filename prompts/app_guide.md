<!--
Hướng dẫn sử dụng TechStoreAI - kho kiến thức cho trợ lý AI đa năng (công cụ app_guide trong app/ai/tools.py).
Mỗi mục bắt đầu bằng "## "; trợ lý tìm mục khớp chủ đề câu hỏi rồi trả lời dựa trên nội dung mục đó.
Khi thêm / đổi chức năng trên giao diện, cập nhật file này để trợ lý hướng dẫn đúng.
-->

## Bán hàng, lập hóa đơn (màn hình Bán hàng / POS)
- Vào menu **Bán hàng**. Bấm vào ô sản phẩm để thêm vào giỏ, hoặc bấm **Quét QR** để quét tem sản phẩm bằng camera, hoặc nhập mã sản phẩm.
- Sản phẩm hết hàng bị làm mờ, không thêm được. Số lượng trong giỏ không được vượt tồn kho.
- Chọn khách hàng: gõ tên hoặc SĐT ở ô khách hàng; bỏ trống = **Khách lẻ**.
- Giảm giá: nhập số tiền (₫) hoặc phần trăm (%). Giảm giá không được lớn hơn tổng tiền hàng.
- Chọn phương thức thanh toán rồi bấm thanh toán. Hóa đơn được tạo với mã dạng HDyyMMddxxxx và tồn kho tự trừ.
- Cả nhân viên và chủ cửa hàng đều bán hàng được.

## Thanh toán: tiền mặt, chuyển khoản, quẹt thẻ, quét mã QR
- **Tiền mặt**: nhập "Tiền khách đưa" để hệ thống tính tiền thừa trả khách; bỏ trống nếu khách đưa đủ. Tiền khách đưa không được ít hơn tổng tiền.
- **Chuyển khoản / Quẹt thẻ**: có thể ghi nội dung chuyển khoản hoặc mã giao dịch POS.
- **Quét mã QR (VietQR)**: hệ thống hiện mã QR có sẵn số tiền và nội dung. Khách mở app ngân hàng bất kỳ, chọn Quét QR. Kiểm tra tài khoản đã nhận tiền rồi bấm xác nhận.
- Tài khoản nhận tiền cấu hình trong file .env (VIETQR_BANK_BIN, VIETQR_ACCOUNT_NO, VIETQR_ACCOUNT_NAME).

## Xem, in, sửa, hủy hóa đơn
- Menu **Hóa đơn**: lọc theo từ khóa (mã hóa đơn, tên / SĐT khách), trạng thái, phương thức thanh toán, khoảng ngày. Bấm một dòng để xem chi tiết và **In hóa đơn**.
- Nhân viên chỉ thấy hóa đơn do mình lập. Chủ cửa hàng thấy tất cả.
- **Sửa hóa đơn** (chỉ chủ cửa hàng): mở chi tiết hóa đơn > **Sửa**. Hệ thống hoàn tồn kho theo dòng cũ rồi trừ theo dòng mới. Không sửa được hóa đơn đã hủy.
- **Hủy hóa đơn** (chỉ chủ cửa hàng): mở chi tiết > **Hủy hóa đơn**, nhập lý do. Tồn kho được hoàn lại, hóa đơn hủy không tính vào doanh thu.
- Chủ cửa hàng xuất danh sách hóa đơn ra Excel (xlsx), CSV hoặc PDF.

## Sản phẩm và nhóm hàng
- Menu **Sản phẩm**: tìm theo tên / mã, lọc theo nhóm, tình trạng tồn (còn hàng, hết hàng, sắp hết), trạng thái.
- Chủ cửa hàng: **Thêm sản phẩm** (mã, tên, nhóm, giá bán, giá vốn, tồn ban đầu, mức tồn tối thiểu, mô tả, ảnh), sửa, xóa. Sản phẩm đã có giao dịch khi xóa sẽ chuyển sang "Ngừng bán".
- Phần **Mô tả** được chatbot dùng để tư vấn, nên ghi rõ tính năng nổi bật.
- Nhân viên xem được sản phẩm nhưng không thấy giá vốn.
- Menu **Nhóm hàng** (chủ cửa hàng): thêm, sửa, xóa nhóm. Không xóa được nhóm đang có sản phẩm.

## In tem QR sản phẩm
- Menu **Sản phẩm** > **In tem QR** (in nhiều sản phẩm) hoặc biểu tượng QR trên từng dòng (chỉ chủ cửa hàng).
- Dán tem lên sản phẩm; ở màn hình Bán hàng bấm **Quét QR** và đưa tem vào camera để thêm vào giỏ.

## Nhập hàng
- Menu **Nhập hàng** (chỉ chủ cửa hàng) > **Tạo phiếu nhập**: chọn nhà cung cấp, thêm từng dòng sản phẩm, số lượng, giá nhập.
- Lưu phiếu: tồn kho tự cộng thêm, giá vốn sản phẩm được cập nhật theo giá nhập gần nhất. Mã phiếu dạng PNyyMMddxxxx.
- Xem lại phiếu cũ bằng cách lọc theo mã phiếu, nhà cung cấp, khoảng ngày.

## Kiểm kho, điều chỉnh tồn kho, nhập - xuất - tồn
- Tồn kho không sửa trực tiếp trong form sản phẩm; nó thay đổi qua bán hàng, phiếu nhập, hủy / sửa hóa đơn hoặc **Kiểm kho**.
- **Kiểm kho** (chỉ chủ cửa hàng): menu Sản phẩm > biểu tượng Kiểm kho trên dòng sản phẩm > nhập "Số lượng thực tế" và "Lý do điều chỉnh".
- Menu **Nhập - xuất - tồn**: nhật ký mọi thay đổi tồn kho (nhập hàng, bán hàng, hủy hóa đơn, sửa hóa đơn, kiểm kho) kèm tồn sau thay đổi.
- Sản phẩm có tồn <= mức tồn tối thiểu được coi là "sắp hết" và hiện cảnh báo ở trang Tổng quan.

## Khách hàng
- Menu **Khách hàng**: tìm theo tên, SĐT, mã; lọc theo nhóm (Thường, VIP, Khách sỉ). Bấm một dòng để xem số hóa đơn, tổng chi tiêu, lần mua gần nhất.
- Nhân viên và chủ cửa hàng đều thêm / sửa được khách hàng; chỉ chủ cửa hàng được xóa. Mã khách tự sinh dạng KH0001.

## Báo cáo doanh thu, tổng quan, xuất file
- Menu **Tổng quan** (chủ cửa hàng): doanh thu hôm nay, tháng này, biểu đồ 30 ngày, sản phẩm bán chạy, cảnh báo sắp hết hàng.
- Menu **Báo cáo doanh thu**: chọn khoảng ngày để xem doanh thu, giảm giá, giá vốn, lãi gộp, biểu đồ theo ngày / tháng, theo nhóm hàng, sản phẩm bán chạy và bán chậm (còn tồn).
- Xuất báo cáo ra Excel (xlsx), CSV hoặc PDF bằng các nút xuất file.
- Chỉ tính hóa đơn đã thanh toán; hóa đơn đã hủy không tính doanh thu.

## Người dùng và phân quyền
- Có 3 vai trò: **Quản trị viên** (toàn quyền, quản lý người dùng), **Chủ cửa hàng** (quản lý hàng hóa, nhập hàng, báo cáo, sửa / hủy hóa đơn, AI báo cáo và hỏi đáp dữ liệu), **Nhân viên bán hàng** (bán hàng, xem hóa đơn của mình, khách hàng, sản phẩm, chatbot).
- Menu **Người dùng** (chỉ quản trị viên): thêm tài khoản, đổi vai trò, đặt lại mật khẩu, khóa / mở tài khoản.

## Các chức năng AI
- **Trợ lý đa năng**: hỏi mọi thứ bằng tiếng Việt tự nhiên: tìm sản phẩm, tồn kho, hóa đơn, khách hàng, doanh thu, cách dùng phần mềm, nhờ viết tin nhắn / nội dung quảng cáo, gợi ý khuyến mãi... AI tự tra dữ liệu thật của cửa hàng qua các công cụ chỉ đọc; không sửa được dữ liệu.
- **Chatbot tư vấn**: mô tả nhu cầu, ngân sách của khách để được gợi ý tối đa 3 sản phẩm còn hàng; bấm "Thêm vào giỏ" để bán ngay.
- **Báo cáo AI** (chủ cửa hàng): chọn kỳ, AI viết nhận xét và khuyến nghị nhập hàng; tải về file .md.
- **Hỏi đáp dữ liệu** (chủ cửa hàng): hỏi về doanh thu, bán chạy, bán chậm, tồn kho theo kỳ.
- Lịch sử trò chuyện được lưu theo từng người dùng: tìm kiếm, đổi tên, xóa ở cột bên trái.
- Khi chưa cấu hình GEMINI_API_KEY trong .env, AI chạy chế độ dự phòng theo từ khóa (hiểu ít loại câu hỏi hơn).

## Đăng nhập, đăng xuất, mật khẩu
- Đăng nhập bằng tên đăng nhập và mật khẩu do quản trị viên cấp. Phiên đăng nhập hết hạn sau 8 giờ.
- Quên mật khẩu: liên hệ quản trị viên để đặt lại trong menu Người dùng.
- Đăng xuất: nút ở góc trên bên phải.
