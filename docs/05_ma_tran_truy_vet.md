# Ma trận truy vết yêu cầu, mã nguồn và kiểm thử

Sinh tự động bằng `python -m scripts.trace_matrix --run` ngày 07/10/2026. Đừng sửa tay: thêm mã test case vào chú thích `# TC-xxx-nn (SRS 11.3)` ngay trên hàm test rồi chạy lại.

Theo SRS mục 11.2, một yêu cầu được xem là hoàn thành khi có mã, có test đạt và có dòng trong ma trận này.

## 1. Tổng hợp

| Chỉ số | Giá trị |
|---|---|
| Test case nghiệp vụ (SRS 11.3) có test tự động đạt | 72 / 72 |
| Yêu cầu chức năng (FR) có nhắc trong mã nguồn | 98 / 153 |
| Yêu cầu chức năng ưu tiên Cao có test | 86 / 86 |

Lần chạy pytest: 307 / 307 hàm test đạt.

## 2. Test case nghiệp vụ (SRS 11.3) và test tự động

| Mã | Tên | Kết quả mong đợi | Test tự động | Trạng thái |
|---|---|---|---|---|
| TC-SAL-01 | Tính hóa đơn mẫu | Tạm tính 18.110.000; giảm 520.000; phải trả 17.590.000; VAT 1.599.091; điểm cộng 2.110 | `tests/test_sales.py::test_checkout_srs_example_updates_points_tier_and_warranty`<br>`tests/test_sales.py::test_preview_matches_srs_example` | Đạt |
| TC-SAL-02 | Chặn bán vượt tồn | Báo lỗi OUT_OF_STOCK, giỏ giữ nguyên | `tests/test_invoices.py::test_insufficient_stock_rejected_and_nothing_changes`<br>`tests/test_srs_acceptance.py::test_out_of_stock_keeps_cart` | Đạt |
| TC-SAL-03 | Bắt chọn serial | Từ chối 422 yêu cầu serial | `tests/test_sales.py::test_serial_must_be_chosen_and_is_marked_sold` | Đạt |
| TC-SAL-04 | Hai quầy bán sản phẩm cuối cùng | Một hóa đơn thành công, một nhận OUT_OF_STOCK, tồn bằng 0 không âm | `tests/test_srs_acceptance.py::test_two_counters_sell_last_item` | Đạt |
| TC-SAL-05 | Giao dịch hoàn tác khi lỗi | Không có hóa đơn, tồn kho và điểm giữ nguyên | `tests/test_srs_acceptance.py::test_transaction_rolls_back_when_warranty_step_fails` | Đạt |
| TC-SAL-06 | Chốt tiền mặt | Tiền thừa 2.410.000, hóa đơn paid | `tests/test_payments_images.py::test_cash_payment_records_change`<br>`tests/test_srs_acceptance.py::test_cash_change_for_sample_invoice` | Đạt |
| TC-SAL-07 | Hủy hóa đơn cùng ngày | Tồn hoàn lại, điểm về 420, voucher giảm used_count, bảo hành void | `tests/test_sales.py::test_cancel_paid_invoice_reverses_points_tier_and_voucher` | Đạt |
| TC-SAL-08 | Nhân viên hủy hóa đơn đã thanh toán | Tạo yêu cầu chờ duyệt, hóa đơn chưa đổi | `tests/test_invoices.py::test_staff_cancel_of_paid_invoice_needs_owner_approval` | Đạt |
| TC-SAL-09 | Hủy hóa đơn khác ngày | Từ chối, hướng dẫn đổi trả | `tests/test_sales.py::test_paid_invoice_can_only_be_cancelled_on_its_day` | Đạt |
| TC-SAL-10 | Hóa đơn chờ chuyển khoản quá hạn | Tự chuyển cancelled, hoàn tồn | `tests/test_sales.py::test_pending_invoice_expires_after_30_minutes` | Đạt |
| TC-SAL-11 | Cảnh báo bán dưới giá vốn | Chặn, chỉ chủ cửa hàng xác nhận được | `tests/test_sales.py::test_staff_cannot_sell_below_cost_but_owner_can` | Đạt |
| TC-SAL-12 | Mã hóa đơn không trùng | 20 mã khác nhau, tăng dần | `tests/test_srs_acceptance.py::test_invoice_codes_unique_under_concurrency` | Đạt |
| TC-PAY-01 | Tạo VietQR | Chuỗi QR có đúng số tiền, nội dung; CRC hợp lệ | `tests/test_payments_images.py::test_crc16_ccitt_known_vector`<br>`tests/test_payments_images.py::test_vietqr_payload_structure` | Đạt |
| TC-PAY-02 | Xác nhận chuyển khoản | Hóa đơn paid, ghi người xác nhận, cộng điểm | `tests/test_sales.py::test_bank_transfer_waits_for_confirmation` | Đạt |
| TC-PAY-03 | PDF hóa đơn tiếng Việt | PDF 80 mm, dấu tiếng Việt hiển thị đúng, có serial | `tests/test_sales.py::test_invoice_pdf_and_reprint`<br>`tests/test_srs_acceptance.py::test_invoice_pdf_80mm_vietnamese_with_serial` | Đạt |
| TC-PAY-04 | Gửi email lỗi không chặn hóa đơn | Hóa đơn vẫn paid, email_logs failed | `tests/test_srs_acceptance.py::test_email_failure_does_not_block_invoice` | Đạt |
| TC-STK-01 | Cảnh báo dưới 5 | Xuất hiện trong danh sách cảnh báo; tồn 5 thì không | `tests/test_inventory.py::test_low_stock_filter`<br>`tests/test_srs_acceptance.py::test_low_stock_warning_threshold` | Đạt |
| TC-STK-02 | Đối chiếu thẻ kho | stock_qty bằng tổng thẻ kho cho mọi sản phẩm | `tests/test_inventory.py::test_stock_movements_logged`<br>`tests/test_srs_acceptance.py::test_stock_card_reconciles_after_mixed_operations` | Đạt |
| TC-STK-03 | Tồn không âm | Từ chối | `tests/test_srs_acceptance.py::test_stock_cannot_go_negative` | Đạt |
| TC-STK-04 | Kiểm kê | Ghi thẻ kho adjust, audit log, bắt buộc lý do | `tests/test_srs_acceptance.py::test_stocktake_requires_reason_and_is_audited`<br>`tests/test_srs_api.py::test_inventory_adjust_and_movements` | Đạt |
| TC-PUR-01 | Xác nhận phiếu nhập | Tồn +20, thẻ kho purchase_in | `tests/test_purchasing.py::test_draft_does_not_change_stock_until_confirmed`<br>`tests/test_srs_acceptance.py::test_confirm_purchase_order_adds_stock` | Đạt |
| TC-PUR-02 | Giá vốn bình quân | Giá vốn mới 210.000 | `tests/test_srs_acceptance.py::test_weighted_average_cost` | Đạt |
| TC-PUR-03 | Serial nhập trùng | Từ chối, liệt kê serial trùng | `tests/test_srs_acceptance.py::test_duplicate_imei_rejected` | Đạt |
| TC-PUR-04 | Lưu nháp không đổi tồn | Tồn không đổi | `tests/test_purchasing.py::test_draft_does_not_change_stock_until_confirmed` | Đạt |
| TC-PUR-05 | Hủy phiếu khi đã bán | Từ chối theo BR-22 | `tests/test_purchasing.py::test_cancel_order_with_sold_serial_is_blocked`<br>`tests/test_purchasing.py::test_cannot_cancel_when_stock_already_sold` | Đạt |
| TC-RET-01 | Đổi trả trong hạn | Hoàn 1.155.831; trừ 138 điểm; tồn +1; hóa đơn partially_returned | `tests/test_aftersales.py::test_return_headset_matches_srs_example` | Đạt |
| TC-RET-02 | Quá 24 giờ | Từ chối RETURN_WINDOW_EXPIRED | `tests/test_aftersales.py::test_return_window_and_status_rules`<br>`tests/test_srs_acceptance.py::test_return_after_window_has_stable_code` | Đạt |
| TC-RET-03 | Serial không khớp | Từ chối dòng | `tests/test_aftersales.py::test_serial_must_match_and_returns_to_stock` | Đạt |
| TC-RET-04 | Hàng lỗi không nhập kho | Tồn không đổi, serial defective | `tests/test_aftersales.py::test_defective_return_does_not_restock` | Đạt |
| TC-RET-05 | Trả vượt số lượng | Từ chối | `tests/test_aftersales.py::test_cannot_return_more_than_bought_or_twice` | Đạt |
| TC-RET-06 | Tính lại hạng | Hạng về Thành viên | `tests/test_srs_acceptance.py::test_return_recomputes_tier` | Đạt |
| TC-WAR-01 | Tự tạo bảo hành | Hồ sơ bảo hành đến cùng ngày sau 12 tháng | `tests/test_srs_acceptance.py::test_warranty_created_for_twelve_months` | Đạt |
| TC-WAR-02 | Tra cứu theo IMEI | Hiển thị đúng hồ sơ, ngày còn lại | `tests/test_aftersales.py::test_warranty_lookup_and_ticket_lifecycle` | Đạt |
| TC-WAR-03 | Từ chối hết hạn | Không tạo phiếu | `tests/test_aftersales.py::test_expired_or_void_warranty_cannot_be_received` | Đạt |
| TC-WAR-04 | Chặn phiếu thứ hai | Từ chối, trả phiếu đang xử lý | `tests/test_aftersales.py::test_warranty_lookup_and_ticket_lifecycle` | Đạt |
| TC-LOY-01 | Điểm theo hạng | Cộng 150 điểm | `tests/test_srs_acceptance.py::test_gold_tier_points` | Đạt |
| TC-LOY-02 | Giới hạn dùng điểm | Tự hạ về mức tối đa | `tests/test_sales.py::test_points_limits` | Đạt |
| TC-PRM-01 | Voucher hết hạn | Báo hết hạn, không áp | `tests/test_sales.py::test_voucher_rejections_explain_reason` | Đạt |
| TC-PRM-02 | Chọn khuyến mãi lớn nhất | Chỉ áp mức giảm tiền lớn hơn | `tests/test_sales.py::test_best_line_promotion_per_product_and_auto_invoice_promo` | Đạt |
| TC-PRM-03 | Hết lượt dùng | Từ chối | `tests/test_srs_acceptance.py::test_voucher_usage_limit` | Đạt |
| TC-AUT-01 | Khóa sau 5 lần sai | Lần 6 báo bị khóa 15 phút | `tests/test_system.py::test_account_locked_after_5_failures_then_admin_unlocks` | Đạt |
| TC-AUT-02 | Phân quyền nhân viên | 403 và không có trường cost_price | `tests/test_invoices.py::test_staff_cannot_see_cost_price`<br>`tests/test_srs_acceptance.py::test_staff_forbidden_reports_and_cost` | Đạt |
| TC-AUT-03 | Token đã thu hồi | 401 | `tests/test_system.py::test_logout_revokes_token` | Đạt |
| TC-AUT-04 | Đặt lại mật khẩu | Lần hai bị từ chối | `tests/test_password_reset.py::test_admin_resets_password_with_emailed_code` | Đạt |
| TC-RPT-01 | Doanh thu ngày | Tổng khớp tổng hóa đơn paid trừ hoàn tiền | `tests/test_reports.py::test_revenue_excludes_cancelled_invoices`<br>`tests/test_srs_acceptance.py::test_daily_revenue_matches_paid_minus_refunds` | Đạt |
| TC-RPT-02 | Lợi nhuận gộp | Doanh thu chưa VAT trừ tổng cost_snapshot | `tests/test_srs_acceptance.py::test_gross_profit_of_sample_invoice` | Đạt |
| TC-RPT-03 | Top bán chạy | Thứ tự theo số lượng đúng | `tests/test_reports.py::test_top_and_slow_products` | Đạt |
| TC-EXP-01 | Xuất Excel | Số dòng và tổng tiền khớp màn hình | `tests/test_reports.py::test_export_formats`<br>`tests/test_srs_acceptance.py::test_excel_export_matches_screen`<br>`tests/test_srs_api.py::test_export_paths` | Đạt |
| TC-EXP-02 | CSV mở được trong Excel | Không lỗi font | `tests/test_reports.py::test_export_formats`<br>`tests/test_srs_acceptance.py::test_csv_has_bom_for_excel` | Đạt |
| TC-AIG-01 | Lọc dữ liệu nhạy cảm | Prompt gửi đi có [SĐT], [EMAIL]; ai_logs đã lọc | `tests/test_srs_acceptance.py::test_sensitive_data_scrubbed_before_ai`<br>`tests/test_system.py::test_ai_calls_are_logged_with_phone_masked` | Đạt |
| TC-AIG-02 | Timeout và thử lại | Thử lại 2 lần rồi báo bận; ai_logs timeout | `tests/test_ai.py::test_gemini_client_timeout`<br>`tests/test_srs_acceptance.py::test_timeout_retries_twice_then_reports_busy` | Đạt |
| TC-AIG-03 | Lỗi 429 | Trả kết quả, retry_count 2 | `tests/test_srs_acceptance.py::test_rate_limit_twice_then_success_counts_retries` | Đạt |
| TC-AIG-04 | Phản hồi sai định dạng | Thử lại một lần; còn sai thì báo lỗi, status invalid_format | `tests/test_ai.py::test_gemini_client_bad_format`<br>`tests/test_srs_acceptance.py::test_advisor_retries_once_on_broken_json`<br>`tests/test_text_to_sql.py::test_invalid_json_falls_back_to_template` | Đạt |
| TC-AIG-05 | Giới hạn lượt | 429 RATE_LIMITED | `tests/test_srs_acceptance.py::test_ai_rate_limit_21st_call`<br>`tests/test_system.py::test_ai_rate_limit_per_hour` | Đạt |
| TC-AIG-06 | Prompt không chứa bí mật | Không có JWT, API key, password_hash | `tests/test_srs_acceptance.py::test_prompts_never_contain_secrets` | Đạt |
| TC-AIA-01 | Tư vấn tai nghe | Hai sản phẩm đúng, không có Sony, không bịa | `tests/test_srs_acceptance.py::test_advisor_narrows_by_category_and_budget` | Đạt |
| TC-AIA-02 | Không có hàng phù hợp | Nói rõ không có | `tests/test_srs_acceptance.py::test_advisor_says_no_match` | Đạt |
| TC-AIA-03 | Loại sản phẩm hết hàng | Không xuất hiện trong prompt | `tests/test_ai.py::test_advisor_v3_sends_only_in_stock_products` | Đạt |
| TC-AIA-04 | Chặn sản phẩm bịa | Câu đó bị loại | `tests/test_ai.py::test_advisor_removes_out_of_stock_and_unknown_suggestions` | Đạt |
| TC-AIA-05 | Dự phòng khi AI lỗi | Hiển thị danh sách lọc thô | `tests/test_ai.py::test_advisor_falls_back_on_ai_error`<br>`tests/test_ai.py::test_fallback_when_ai_disabled` | Đạt |
| TC-AIA-06 | Prompt injection trong mô tả | Câu trả lời không đổi vai trò | `tests/test_srs_acceptance.py::test_injection_in_description_is_data` | Đạt |
| TC-AIR-01 | Báo cáo đủ mục | Có đủ bốn mục | `tests/test_ai.py::test_ai_report_falls_back_on_bad_format`<br>`tests/test_srs_acceptance.py::test_ai_report_has_four_sections` | Đạt |
| TC-AIR-02 | Số liệu khớp | Khớp; lệch thì thử lại | `tests/test_srs_acceptance.py::test_ai_report_numbers_must_match` | Đạt |
| TC-AIR-03 | Không gửi dữ liệu khách | Không có tên, số điện thoại, mã hóa đơn | `tests/test_ai.py::test_ai_report_does_not_leak_customer_pii`<br>`tests/test_srs_acceptance.py::test_ai_report_payload_has_no_customer_or_invoice` | Đạt |
| TC-AIQ-01 | Câu hỏi bán chậm | SQL SELECT trên view; câu trả lời liệt kê đúng 3 mặt hàng bán ít nhất | `tests/test_ai.py::test_ask_data_uses_system_data`<br>`tests/test_text_to_sql.py::test_srs_example_is_accepted` | Đạt |
| TC-AIQ-02 | Từ chối SQL ghi | Không chạy, rejected_sql | `tests/test_text_to_sql.py::test_rejected_sql`<br>`tests/test_text_to_sql.py::test_rejected_sql_is_not_run_and_logged` | Đạt |
| TC-AIQ-03 | Từ chối bảng gốc | Không chạy | `tests/test_text_to_sql.py::test_rejected_sql` | Đạt |
| TC-AIQ-04 | Nhiều câu lệnh | Không chạy | `tests/test_text_to_sql.py::test_rejected_sql` | Đạt |
| TC-AIQ-05 | Kết nối chỉ đọc | Lỗi readonly | `tests/test_text_to_sql.py::test_connection_is_read_only_even_if_guard_bypassed`<br>`tests/test_text_to_sql.py::test_readonly_file_database` | Đạt |
| TC-AIQ-06 | Giới hạn dòng và thời gian | Cắt 200 dòng; dừng sau 5 giây | `tests/test_text_to_sql.py::test_run_sql_limit_200`<br>`tests/test_text_to_sql.py::test_run_sql_timeout` | Đạt |
| TC-AIQ-07 | Kết quả rỗng | Nói rõ không có dữ liệu | `tests/test_text_to_sql.py::test_empty_result_is_sent_for_interpretation` | Đạt |
| TC-AIQ-08 | Nhân viên bị cấm | 403 | `tests/test_text_to_sql.py::test_staff_cannot_ask` | Đạt |

## 3. Yêu cầu, use case, mã nguồn và test

Cột *Test* gồm test của các test case SRS gắn với yêu cầu và các test nhắc trực tiếp mã yêu cầu.

| Yêu cầu | Ưu tiên | Use case | Test case SRS | Có trong mã | Test | Trạng thái |
|---|---|---|---|---|---|---|
| FR-AIA-01 | Cao | UC-45 | TC-AIA-01 | - | 1 test | Đạt |
| FR-AIA-02 | Cao | UC-45 | TC-AIA-01, TC-AIA-03 | `app/ai/service.py`<br>`prompts/product_advisor_v3.md` | 2 test | Đạt |
| FR-AIA-03 | Cao | UC-45 | TC-AIA-02 | - | 1 test | Đạt |
| FR-AIA-04 | Cao | UC-45 | TC-AIA-01, TC-AIA-04 | - | 2 test | Đạt |
| FR-AIA-05 | Trung bình | UC-45 | - | - | 0 test | - |
| FR-AIA-06 | Trung bình | UC-45 | TC-AIA-05 | - | 2 test | Đạt |
| FR-AIA-07 | Thấp | UC-45 | - | `app/ai/service.py`<br>`app/routers/ai.py`<br>`app/schemas.py` ... | 4 test | Đạt |
| FR-AIA-08 | Thấp | UC-45 | - | `app/ai/history.py`<br>`app/ai/service.py` | 1 test | Đạt |
| FR-AIG-01 | Cao | UC-08, UC-45 | - | - | 4 test | Đạt |
| FR-AIG-02 | Cao | UC-08 | - | - | 1 test | Đạt |
| FR-AIG-03 | Cao | UC-45, UC-46, UC-47 | TC-AIG-01 | `app/ai/assistant.py`<br>`app/ai/sanitizer.py`<br>`app/ai/service.py` | 2 test | Đạt |
| FR-AIG-04 | Cao | UC-45 | TC-AIG-02, TC-AIG-03 | - | 3 test | Đạt |
| FR-AIG-05 | Cao | UC-45, UC-46, UC-47 | TC-AIG-04 | `app/ai/service.py` | 3 test | Đạt |
| FR-AIG-06 | Trung bình | UC-45 | TC-AIG-05 | - | 2 test | Đạt |
| FR-AIG-07 | Cao | UC-48 | - | - | 2 test | Đạt |
| FR-AIG-08 | Trung bình | UC-08 | - | - | 4 test | Đạt |
| FR-AIG-09 | Trung bình | UC-45 | TC-AIA-06 | `prompts/product_advisor_v3.md` | 1 test | Đạt |
| FR-AIQ-01 | Cao | UC-47 | TC-AIQ-01 | - | 2 test | Đạt |
| FR-AIQ-02 | Cao | UC-47 | TC-AIQ-01 | `app/ai/text_to_sql.py`<br>`prompts/sales_sql.md` | 2 test | Đạt |
| FR-AIQ-03 | Cao | UC-47 | TC-AIQ-03 | - | 1 test | Đạt |
| FR-AIQ-04 | Cao | UC-47 | TC-AIQ-02, TC-AIQ-04 | - | 2 test | Đạt |
| FR-AIQ-05 | Cao | UC-47 | TC-AIQ-06 | `app/ai/text_to_sql.py` | 2 test | Đạt |
| FR-AIQ-06 | Cao | UC-47 | TC-AIQ-07 | `prompts/sales_qa.md` | 1 test | Đạt |
| FR-AIQ-07 | Trung bình | UC-47 | - | `frontend/src/pages/AIChat.jsx` | 0 test | Có mã, chưa có test |
| FR-AIQ-08 | Trung bình | UC-47 | - | `app/ai/service.py` | 0 test | Có mã, chưa có test |
| FR-AIR-01 | Cao | UC-46 | - | `app/services/reports.py` | 1 test | Đạt |
| FR-AIR-02 | Cao | UC-46 | TC-AIR-03 | `prompts/sales_report.md` | 2 test | Đạt |
| FR-AIR-03 | Cao | UC-46 | TC-AIR-01 | `app/ai/service.py`<br>`prompts/sales_report.md` | 2 test | Đạt |
| FR-AIR-04 | Trung bình | UC-46 | TC-AIR-02 | `app/ai/service.py` | 1 test | Đạt |
| FR-AIR-05 | Trung bình | UC-46 | - | `app/ai/service.py` | 0 test | Có mã, chưa có test |
| FR-AIR-06 | Thấp | UC-46, UC-44 | - | `app/routers/ai.py`<br>`app/services/export.py`<br>`frontend/src/pages/AIReport.jsx` | 1 test | Đạt |
| FR-AUT-01 | Cao | UC-01 | - | `app/routers/auth.py` | 1 test | Đạt |
| FR-AUT-02 | Cao | UC-01 | - | - | 1 test | Đạt |
| FR-AUT-03 | Cao | UC-01 | TC-AUT-01 | `app/models.py` | 1 test | Đạt |
| FR-AUT-04 | Cao | UC-01 | - | - | 1 test | Đạt |
| FR-AUT-05 | Cao | UC-02 | TC-AUT-03 | `app/models.py`<br>`app/routers/auth.py`<br>`app/security.py` | 1 test | Đạt |
| FR-AUT-06 | Trung bình | UC-04 | TC-AUT-04 | `app/routers/auth.py` | 1 test | Đạt |
| FR-AUT-07 | Trung bình | UC-03 | - | `app/routers/auth.py`<br>`app/security.py` | 0 test | Có mã, chưa có test |
| FR-AUT-08 | Cao | UC-01 | TC-AUT-02 | - | 8 test | Đạt |
| FR-AUT-09 | Trung bình | UC-01 | - | `frontend/src/auth.jsx` | 0 test | Có mã, chưa có test |
| FR-CAT-01 | Cao | UC-10 | - | - | 3 test | Đạt |
| FR-CAT-02 | Trung bình | UC-10 | - | - | 1 test | Đạt |
| FR-CAT-03 | Trung bình | UC-10 | - | `app/routers/catalog.py` | 0 test | Có mã, chưa có test |
| FR-CUS-01 | Cao | UC-14 | - | - | 3 test | Đạt |
| FR-CUS-02 | Cao | UC-14 | - | `app/schemas.py` | 1 test | Đạt |
| FR-CUS-03 | Cao | UC-14, UC-19 | - | `app/routers/customers.py` | 1 test | Đạt |
| FR-CUS-04 | Trung bình | UC-15 | - | `app/routers/customers.py` | 0 test | Có mã, chưa có test |
| FR-CUS-05 | Trung bình | UC-14 | - | `app/routers/customers.py` | 0 test | Có mã, chưa có test |
| FR-CUS-06 | Thấp | UC-14 | - | `app/schemas.py` | 0 test | Có mã, chưa có test |
| FR-EXP-01 | Cao | UC-44 | TC-EXP-01 | `app/routers/reports.py`<br>`frontend/src/pages/Reports.jsx` | 3 test | Đạt |
| FR-EXP-02 | Trung bình | UC-44 | - | - | 0 test | - |
| FR-EXP-03 | Trung bình | UC-44 | TC-EXP-02 | - | 2 test | Đạt |
| FR-EXP-04 | Trung bình | UC-44 | - | `app/routers/reports.py` | 0 test | Có mã, chưa có test |
| FR-LOY-01 | Trung bình | UC-16 | - | `app/routers/loyalty.py`<br>`frontend/src/pages/Settings.jsx` | 0 test | Có mã, chưa có test |
| FR-LOY-02 | Trung bình | UC-16, UC-31 | TC-RET-06 | - | 1 test | Đạt |
| FR-LOY-03 | Cao | UC-19 | TC-LOY-01 | - | 1 test | Đạt |
| FR-LOY-04 | Trung bình | UC-22 | TC-LOY-02 | - | 1 test | Đạt |
| FR-LOY-05 | Thấp | UC-17 | - | `app/routers/customers.py` | 0 test | Có mã, chưa có test |
| FR-LOY-06 | Thấp | UC-15 | - | `app/routers/customers.py` | 0 test | Có mã, chưa có test |
| FR-PAY-01 | Cao | UC-23 | TC-SAL-06 | - | 2 test | Đạt |
| FR-PAY-02 | Trung bình | UC-25 | - | - | 0 test | - |
| FR-PAY-03 | Cao | UC-24 | TC-PAY-01 | `app/routers/invoices.py` | 2 test | Đạt |
| FR-PAY-04 | Trung bình | UC-24 | - | - | 0 test | - |
| FR-PAY-05 | Cao | UC-24 | TC-PAY-02 | `app/routers/invoices.py`<br>`app/services/sales.py` | 1 test | Đạt |
| FR-PAY-06 | Thấp | UC-24 | - | `app/schemas.py` | 0 test | Có mã, chưa có test |
| FR-PAY-07 | Cao | UC-26 | TC-PAY-03 | `app/routers/invoices.py`<br>`app/services/receipts.py` | 2 test | Đạt |
| FR-PAY-08 | Trung bình | UC-26 | - | `app/services/receipts.py` | 0 test | Có mã, chưa có test |
| FR-PAY-09 | Trung bình | UC-26 | - | - | 0 test | - |
| FR-PAY-10 | Trung bình | UC-27 | TC-PAY-04 | `app/routers/invoices.py`<br>`app/services/mailer.py` | 1 test | Đạt |
| FR-PRD-01 | Cao | UC-11 | - | - | 2 test | Đạt |
| FR-PRD-02 | Cao | UC-11 | - | - | 4 test | Đạt |
| FR-PRD-03 | Cao | UC-11 | - | `app/services/sales.py` | 2 test | Đạt |
| FR-PRD-04 | Trung bình | UC-11 | - | - | 2 test | Đạt |
| FR-PRD-05 | Trung bình | UC-11 | - | `app/routers/catalog.py` | 0 test | Có mã, chưa có test |
| FR-PRD-06 | Cao | UC-13 | - | `app/routers/catalog.py` | 3 test | Đạt |
| FR-PRD-07 | Cao | UC-13 | - | `app/routers/catalog.py` | 2 test | Đạt |
| FR-PRD-08 | Cao | UC-11, UC-13 | - | `app/routers/catalog.py` | 1 test | Đạt |
| FR-PRD-09 | Cao | UC-12 | - | `app/models.py` | 3 test | Đạt |
| FR-PRD-10 | Cao | UC-12 | - | - | 2 test | Đạt |
| FR-PRM-01 | Cao | UC-18 | - | - | 2 test | Đạt |
| FR-PRM-02 | Cao | UC-18 | - | - | 2 test | Đạt |
| FR-PRM-03 | Cao | UC-18 | TC-PRM-03 | - | 1 test | Đạt |
| FR-PRM-04 | Cao | UC-18 | - | - | 2 test | Đạt |
| FR-PRM-05 | Cao | UC-21 | - | `app/services/sales.py` | 2 test | Đạt |
| FR-PRM-06 | Cao | UC-21 | TC-PRM-01, TC-PRM-02 | `app/routers/promotions.py`<br>`app/services/pricing.py` | 2 test | Đạt |
| FR-PRM-07 | Trung bình | UC-18 | - | `app/routers/promotions.py`<br>`app/services/pricing.py` | 0 test | Có mã, chưa có test |
| FR-PUR-01 | Cao | UC-36 | - | - | 1 test | Đạt |
| FR-PUR-02 | Cao | UC-36 | TC-PUR-04 | `app/routers/purchasing.py` | 1 test | Đạt |
| FR-PUR-03 | Cao | UC-36 | TC-PUR-03 | `app/services/purchasing.py` | 1 test | Đạt |
| FR-PUR-04 | Cao | UC-36 | TC-PUR-01 | `app/services/purchasing.py` | 2 test | Đạt |
| FR-PUR-05 | Cao | UC-36 | TC-PUR-02 | - | 1 test | Đạt |
| FR-PUR-06 | Trung bình | UC-37 | TC-PUR-05 | `app/services/purchasing.py` | 2 test | Đạt |
| FR-PUR-07 | Trung bình | UC-36 | - | - | 2 test | Đạt |
| FR-PUR-08 | Cao | UC-36 | - | `app/routers/purchasing.py` | 2 test | Đạt |
| FR-RET-01 | Cao | UC-31 | - | `app/routers/aftersales.py` | 2 test | Đạt |
| FR-RET-02 | Cao | UC-31 | TC-RET-01, TC-RET-02 | `app/services/aftersales.py` | 3 test | Đạt |
| FR-RET-03 | Cao | UC-31 | TC-RET-05 | `app/services/aftersales.py` | 1 test | Đạt |
| FR-RET-04 | Cao | UC-31 | TC-RET-03 | `app/schemas.py`<br>`app/services/aftersales.py` | 1 test | Đạt |
| FR-RET-05 | Cao | UC-31 | TC-RET-01 | - | 1 test | Đạt |
| FR-RET-06 | Cao | UC-31 | TC-RET-04 | - | 1 test | Đạt |
| FR-RET-07 | Trung bình | UC-31 | - | - | 0 test | - |
| FR-RET-08 | Trung bình | UC-31 | - | `app/routers/aftersales.py` | 0 test | Có mã, chưa có test |
| FR-RPT-01 | Cao | UC-41 | - | `frontend/src/pages/Dashboard.jsx` | 2 test | Đạt |
| FR-RPT-02 | Cao | UC-42 | TC-RPT-01 | `frontend/src/pages/Reports.jsx` | 2 test | Đạt |
| FR-RPT-03 | Cao | UC-42 | - | - | 2 test | Đạt |
| FR-RPT-04 | Cao | UC-42 | TC-RPT-03 | `app/services/reports.py` | 1 test | Đạt |
| FR-RPT-05 | Trung bình | UC-42 | TC-RPT-02 | `app/services/reports.py` | 2 test | Đạt |
| FR-RPT-06 | Trung bình | UC-42 | - | `app/services/reports.py` | 1 test | Đạt |
| FR-RPT-07 | Trung bình | UC-43 | - | `app/services/reports.py` | 0 test | Có mã, chưa có test |
| FR-RPT-08 | Trung bình | UC-42 | - | - | 0 test | - |
| FR-SAL-01 | Cao | UC-19, UC-20 | - | `app/routers/catalog.py`<br>`frontend/src/pages/Pos.jsx` | 1 test | Đạt |
| FR-SAL-02 | Cao | UC-19 | - | - | 2 test | Đạt |
| FR-SAL-03 | Cao | UC-19 | TC-SAL-02 | `app/services/sales.py` | 2 test | Đạt |
| FR-SAL-04 | Cao | UC-19, UC-20 | TC-SAL-03 | `app/schemas.py`<br>`app/services/sales.py` | 1 test | Đạt |
| FR-SAL-05 | Cao | UC-19, UC-21 | TC-SAL-01 | `app/services/pricing.py`<br>`app/services/sales.py`<br>`frontend/src/pages/Pos.jsx` | 2 test | Đạt |
| FR-SAL-06 | Cao | UC-19 | - | - | 2 test | Đạt |
| FR-SAL-07 | Trung bình | UC-19 | - | `app/routers/invoices.py`<br>`app/services/sales.py`<br>`frontend/src/pages/Pos.jsx` | 0 test | Có mã, chưa có test |
| FR-SAL-08 | Cao | UC-19 | TC-SAL-04, TC-SAL-05 | `app/services/sales.py` | 2 test | Đạt |
| FR-SAL-09 | Cao | UC-29 | TC-SAL-07, TC-SAL-09 | `app/services/sales.py` | 2 test | Đạt |
| FR-SAL-10 | Trung bình | UC-29 | TC-SAL-08 | `app/models.py`<br>`app/services/sales.py` | 1 test | Đạt |
| FR-SAL-11 | Trung bình | UC-28 | - | `app/routers/invoices.py` | 0 test | Có mã, chưa có test |
| FR-SAL-12 | Cao | UC-19 | TC-SAL-12 | `app/database.py`<br>`app/routers/aftersales.py`<br>`app/routers/invoices.py` ... | 1 test | Đạt |
| FR-SAL-13 | Cao | UC-30 | - | `app/routers/invoices.py` | 4 test | Đạt |
| FR-SAL-14 | Trung bình | UC-19 | TC-SAL-11 | `app/services/sales.py` | 1 test | Đạt |
| FR-SAL-15 | Trung bình | UC-24 | TC-SAL-10 | `app/services/sales.py` | 1 test | Đạt |
| FR-STK-01 | Cao | UC-19, UC-29, UC-31, UC-36 | TC-STK-03 | - | 1 test | Đạt |
| FR-STK-02 | Cao | UC-38 | TC-STK-01 | `app/routers/inventory.py`<br>`app/services/reports.py`<br>`frontend/src/Shell.jsx` | 2 test | Đạt |
| FR-STK-03 | Cao | UC-40 | TC-STK-02 | - | 2 test | Đạt |
| FR-STK-04 | Trung bình | UC-39 | TC-STK-04 | `app/routers/inventory.py`<br>`app/services/inventory.py` | 2 test | Đạt |
| FR-STK-05 | Trung bình | UC-40 | - | `app/routers/catalog.py`<br>`app/routers/inventory.py` | 0 test | Có mã, chưa có test |
| FR-STK-06 | Cao | UC-19 | TC-SAL-04 | `app/services/inventory.py` | 1 test | Đạt |
| FR-SUP-01 | Cao | UC-35 | - | - | 1 test | Đạt |
| FR-SUP-02 | Trung bình | UC-35 | - | `app/routers/purchasing.py` | 0 test | Có mã, chưa có test |
| FR-SUP-03 | Trung bình | UC-35 | - | `app/routers/purchasing.py` | 0 test | Có mã, chưa có test |
| FR-SUP-04 | Thấp | UC-35 | - | `app/routers/purchasing.py` | 0 test | Có mã, chưa có test |
| FR-SYS-01 | Cao | UC-09 | - | - | 1 test | Đạt |
| FR-SYS-02 | Trung bình | UC-07, UC-08 | - | `app/services/app_settings.py` | 0 test | Có mã, chưa có test |
| FR-SYS-03 | Trung bình | UC-06 | - | `app/models.py`<br>`app/services/audit.py` | 0 test | Có mã, chưa có test |
| FR-SYS-04 | Thấp | UC-09 | - | `app/routers/system.py`<br>`frontend/src/pages/Backup.jsx` | 0 test | Có mã, chưa có test |
| FR-SYS-05 | Thấp | UC-08 | - | - | 0 test | - |
| FR-USR-01 | Cao | UC-05 | - | `app/routers/auth.py`<br>`frontend/src/pages/Users.jsx` | 2 test | Đạt |
| FR-USR-02 | Trung bình | UC-05 | - | `app/models.py`<br>`app/routers/auth.py`<br>`app/schemas.py` ... | 0 test | Có mã, chưa có test |
| FR-USR-03 | Cao | UC-05 | - | `app/routers/auth.py` | 3 test | Đạt |
| FR-USR-04 | Trung bình | UC-05 | - | `app/routers/auth.py` | 0 test | Có mã, chưa có test |
| FR-USR-05 | Trung bình | UC-05, UC-06 | - | - | 2 test | Đạt |
| FR-WAR-01 | Cao | UC-19, UC-32 | TC-WAR-01 | `app/models.py`<br>`app/services/sales.py`<br>`frontend/src/pages/Warranty.jsx` | 1 test | Đạt |
| FR-WAR-02 | Cao | UC-32 | TC-WAR-02 | `app/services/aftersales.py` | 1 test | Đạt |
| FR-WAR-03 | Cao | UC-33 | TC-WAR-03 | - | 1 test | Đạt |
| FR-WAR-04 | Trung bình | UC-33 | TC-WAR-04 | `app/services/aftersales.py` | 1 test | Đạt |
| FR-WAR-05 | Trung bình | UC-33 | - | `app/routers/aftersales.py` | 0 test | Có mã, chưa có test |
| FR-WAR-06 | Thấp | UC-33 | - | `app/routers/aftersales.py` | 0 test | Có mã, chưa có test |
| FR-WAR-07 | Trung bình | UC-34 | - | `app/services/aftersales.py` | 0 test | Có mã, chưa có test |
| FR-WAR-08 | Thấp | UC-34 | - | - | 0 test | - |
| NFR-AIQ-01 | Cao | - | - | - | 0 test | - |
| NFR-AIQ-02 | Trung bình | - | - | - | 0 test | - |
| NFR-AIQ-03 | Cao | - | TC-AIQ-05 | - | 2 test | Đạt |
| NFR-AIQ-04 | Trung bình | - | - | - | 0 test | - |
| NFR-AIQ-05 | Cao | - | - | - | 0 test | - |
| NFR-DAT-01 | Cao | - | TC-AIG-01 | `app/services/ai_log.py`<br>`frontend/src/pages/AIReport.jsx` | 2 test | Đạt |
| NFR-DAT-02 | Trung bình | - | - | - | 0 test | - |
| NFR-DAT-03 | Trung bình | - | - | - | 0 test | - |
| NFR-DAT-04 | Thấp | - | - | - | 0 test | - |
| NFR-DAT-05 | Thấp | - | - | - | 0 test | - |
| NFR-LEG-01 | Trung bình | - | - | - | 0 test | - |
| NFR-LEG-02 | Trung bình | - | - | - | 0 test | - |
| NFR-LEG-03 | Trung bình | - | - | - | 0 test | - |
| NFR-MNT-01 | Cao | - | - | - | 0 test | - |
| NFR-MNT-02 | Trung bình | - | - | - | 0 test | - |
| NFR-MNT-03 | Thấp | - | - | - | 0 test | - |
| NFR-MNT-04 | Cao | - | - | - | 0 test | - |
| NFR-MNT-05 | Cao | - | - | - | 0 test | - |
| NFR-MNT-06 | Thấp | - | - | - | 0 test | - |
| NFR-MNT-07 | Thấp | - | - | - | 0 test | - |
| NFR-PER-01 | Cao | - | - | - | 0 test | - |
| NFR-PER-02 | Cao | - | - | - | 0 test | - |
| NFR-PER-03 | Cao | - | - | - | 0 test | - |
| NFR-PER-04 | Trung bình | - | - | - | 0 test | - |
| NFR-PER-05 | Trung bình | - | - | - | 0 test | - |
| NFR-PER-06 | Trung bình | - | - | `frontend/src/pages/AILogs.jsx` | 0 test | Có mã, chưa có test |
| NFR-PER-07 | Cao | - | - | - | 0 test | - |
| NFR-POR-01 | Trung bình | - | - | - | 0 test | - |
| NFR-POR-02 | Cao | - | - | - | 0 test | - |
| NFR-POR-03 | Cao | - | - | - | 0 test | - |
| NFR-POR-04 | Thấp | - | - | - | 0 test | - |
| NFR-POR-05 | Trung bình | - | - | - | 0 test | - |
| NFR-POR-06 | Trung bình | - | - | - | 0 test | - |
| NFR-REL-01 | Cao | - | - | - | 0 test | - |
| NFR-REL-02 | Cao | - | TC-STK-02 | - | 2 test | Đạt |
| NFR-REL-03 | Trung bình | - | - | - | 0 test | - |
| NFR-REL-04 | Trung bình | - | - | - | 0 test | - |
| NFR-REL-05 | Cao | - | - | - | 1 test | Đạt |
| NFR-REL-06 | Thấp | - | - | - | 0 test | - |
| NFR-SEC-01 | Cao | - | - | - | 0 test | - |
| NFR-SEC-02 | Cao | - | - | - | 0 test | - |
| NFR-SEC-03 | Cao | - | TC-AIQ-08 | - | 1 test | Đạt |
| NFR-SEC-04 | Trung bình | - | - | - | 0 test | - |
| NFR-SEC-05 | Cao | - | - | - | 0 test | - |
| NFR-SEC-06 | Trung bình | - | - | `frontend/src/ui/Markdown.jsx` | 0 test | Có mã, chưa có test |
| NFR-SEC-07 | Trung bình | - | - | - | 0 test | - |
| NFR-SEC-08 | Cao | - | TC-AIG-06 | - | 2 test | Đạt |
| NFR-SEC-09 | Cao | - | TC-AUT-02 | - | 2 test | Đạt |
| NFR-SEC-10 | Trung bình | - | - | `app/routers/product_import.py` | 0 test | Có mã, chưa có test |
| NFR-SEC-11 | Trung bình | - | - | - | 0 test | - |
| NFR-USA-01 | Trung bình | - | - | - | 0 test | - |
| NFR-USA-02 | Trung bình | - | - | - | 0 test | - |
| NFR-USA-03 | Trung bình | - | - | - | 0 test | - |
| NFR-USA-04 | Thấp | - | - | - | 0 test | - |
| NFR-USA-05 | Trung bình | - | - | - | 0 test | - |
