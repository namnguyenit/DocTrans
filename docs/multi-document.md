# Dịch nhiều tài liệu

## Sử dụng

- Chọn **Dịch nhiều tài liệu...**, chọn nhiều file PDF/DOCX/TXT/Markdown.
  Có thể thêm file khi các tài liệu khác đang dịch hoặc kéo thả nhiều file
  vào cửa sổ. Chọn lại file đang mở sẽ chuyển đến tab đó thay vì dịch trùng.
- Mỗi tài liệu có một tab và dòng tiến độ riêng trong thanh bên. Chuyển tab
  hoặc chuyển sang Đọc Đơn không dừng công việc nền.
- **Hủy** trong tab dừng tài liệu đó; **Tiếp tục dịch** chạy phần còn lại.
  Đóng tab loại bỏ công việc của riêng tài liệu đó.
- **Xuất tất cả bản dịch...** lưu các tài liệu đã hoàn tất thành PDF riêng
  trong thư mục chọn. File trùng tên được thêm hậu tố `_2`, `_3`...; việc ghi
  dùng file tạm rồi hoàn tất bằng QSaveFile. Không xuất các tài liệu còn lỗi
  hoặc chưa dịch xong. TXT/DOCX/Markdown xuất nội dung đã dịch và tự phân trang;
  PDF giữ cách xuất ảnh trang với chữ dịch đè lên bố cục gốc.
- PDF có mật khẩu yêu cầu nhập riêng cho file đó. Một file đọc lỗi không dừng
  các file khác. Ảnh riêng vẫn chỉ hỗ trợ xem như trước, chưa có luồng dịch OCR
  cho ảnh riêng.

## Cách giữ GPU có việc

Một `OfflineTranslator` và một tiến trình Python phục vụ toàn bộ cửa sổ.
Chỉ nạp một VinAI và một mô hình hiệu đính vào VRAM, không nạp mô hình theo
số tab. Cấu hình hiện tại trên máy thử là Qwen3.5-4B Q6_K qua llama.cpp CUDA.

1. Tối đa hai tác vụ đọc tài liệu chạy bằng QtConcurrent. Trong khi GPU dịch
   các file đã chuẩn bị, CPU có thể trích xuất PDF/OCR và đọc file kế tiếp.
2. Mỗi tab gửi các đơn vị dịch vào hàng đợi riêng. Bộ điều phối chung lấy
   luân phiên giữa các tài liệu, gom tối đa 32 yêu cầu VinAI mỗi lượt.
3. Chỉ có tối đa **96 yêu cầu** được gửi vào backend mà chưa kết thúc bước
   hiệu đính. Khi mô hình trả kết quả cuối, chỗ trống được cấp ngay cho công việc
   tiếp theo. VinAI không tạo một hàng đợi bản thô không giới hạn.
4. Worker gom tối đa 24 prompt độc lập, có giới hạn tổng token. Engine CUDA
   xử lý bằng 8 slot liên tục, cấp câu tiếp theo khi một slot kết thúc. Backend
   PyTorch vẫn ghép lô và chia nhỏ khi OOM. Mỗi prompt nhận ngữ cảnh nguồn từ
   chính tài liệu của nó; mã yêu cầu là duy nhất trong toàn phiên.
5. Bản thô được trả trước khi công việc vào worker hiệu đính. Bản thô đến
   trong lúc mô hình đang nạp được giữ lại chờ; hàng đợi đầy tạo backpressure
   thay vì bỏ bước hiệu đính. Nếu mô hình không nạp được, ứng dụng giữ bản thô
   và hiển thị trạng thái mô hình.
6. Chỉ tab đang xem dựng ảnh PDF và cập nhật phần đọc. Các tab nền cập nhật
   số lượng hoàn tất; thanh bên được gom cập nhật khoảng 100 ms một lần.

Hai mô hình cùng dùng một GPU. Khóa GPU chung giới hạn các lượt sinh chồng
đỉnh VRAM; vì vậy mô hình nhanh hơn có thể chờ mô hình chậm hơn. Mục tiêu là
giảm khoảng trống của GPU và tăng lượng tài liệu hoàn tất, không bảo đảm cả
hai mô hình luôn tính toán đồng thời hoặc chỉ số GPU luôn bằng 100%.

## Cách ly và phục hồi

- Mỗi tab có mã client; request ID cấp từ bộ đếm dùng chung và không tái sử
  dụng khi chuyển tab hoặc khởi động lại backend. Kết quả cũ không ghi vào
  tài liệu khác.
- Dừng/đóng một tab chỉ hủy các yêu cầu của client đó. Yêu cầu đang xử lý giữ
  chỗ trong giới hạn cho đến khi backend xác nhận kết thúc/hủy.
- Chuyển trang/tab không gửi lặp các đơn vị đang chờ hoặc đang xử lý.
- Khi một phần lỗi, tài liệu đó hiển thị lỗi và có thể tiếp tục; tài liệu
  khác vẫn chạy. Khởi động lại mô hình dùng chung phục hồi các yêu cầu còn lại.
- SQLite và cache trong RAM dùng khóa chung giữa các worker. Xóa cache không
  xóa hàng đợi dịch của các tài liệu đang chạy.
- Danh sách tab nằm trong phiên hiện tại. Bộ nhớ dịch SQLite vẫn dùng lại
  khi mở tài liệu lần sau; không lưu toàn bộ danh sách hàng đợi để tự phục
  hồi sau khi thoát ứng dụng.

## Kiểm tra

Đã build và kiểm tra trên Windows với RTX 4070 Laptop 8 GB. Chưa kiểm tra lại
giao diện và runtime trên macOS/Linux trong đợt thay đổi này.

- 21 kiểm thử pipeline Python: batching, token budget, OOM giả lập, giữ hàng đợi khi
  đang nạp, backpressure, thứ tự raw/polish, hủy từng tài liệu và giữ công việc
  khi xóa cache, ngữ cảnh/cache và lỗi engine native. Thêm 3 kiểm thử giao
  thức loopback, thứ tự phản hồi và đóng tiến trình native khi chủ sở hữu bị kill.
- Kiểm thử C++ cho round-robin, giới hạn cửa sổ, cấp lại chỗ và request ID.
- Kiểm thử ứng dụng với backend giao thức giả: nhiều file PDF/TXT/Markdown,
  xuất PDF, chống kết quả lẫn giữa file, không mở trùng, chuyển tab nhiều lần,
  đóng file đang dịch, dừng/tiếp tục và cô lập một file lỗi.
- Thử mô hình thật: ba tài liệu ban đầu dịch và xuất PDF; sau đó thêm bốn file,
  tổng 128 đoạn, vượt cửa sổ 96 để kiểm tra cấp tiếp công việc. Báo cáo kết quả
  của cấu hình hiện tại nằm trong `build/multi_document_qwen35.json`; ảnh ở
  `build/multi_document_qwen35.png`. Bộ nhớ dịch được chuyển vào thư mục tạm
  cho lần kiểm tra, không dùng tài liệu cá nhân.

Lượt đo Qwen3.5 trên máy này hoàn tất 128 đoạn của bốn file trong khoảng **35,0 giây**,
gồm chuẩn bị file và cả hai bước dịch/hiệu đính, sau khi mô hình đã nạp. Có đúng
128 yêu cầu dịch cho 128 đoạn, không có công việc gửi lặp trong phần đo này.
Đây là mẫu đoạn kỹ thuật ngắn, không phải cam kết thời gian cho PDF scan hoặc
tài liệu có đoạn dài.

Lượt VyLinh trước đó khoảng 33,0 giây trên cùng phần thử 128 đoạn. Cấu hình
mới ưu tiên sửa chất lượng ngữ cảnh; không tuyên bố nhanh hơn ở phép thử cả
luồng này. Dữ liệu đối chiếu mô hình và tối ưu CUDA riêng tại
[so sánh mô hình](model-comparison.md) và [tối ưu GPU](gpu-tuning.md).

```powershell
ctest --test-dir build -R "translation_scheduler|polish_pipeline|multi_document|cuda_server" --output-on-failure
```

Các lỗi kiểm thử bố cục PDF đã được phát hiện trước đó không được sửa trong
phạm vi tính năng này.

Tham chiếu Qt cho tác vụ đọc nền:
[Qt threading classes và QFutureWatcher](https://doc.qt.io/qt-6/threads.html).
