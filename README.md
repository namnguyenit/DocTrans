# readDoc — Trình đọc và dịch tài liệu ngoại tuyến

readDoc là ứng dụng C++20/Qt 6 cho macOS và Linux x86_64. Ứng dụng đọc tài
liệu cục bộ và dịch Anh–Việt hoàn toàn trên máy, không gọi API dịch và không
gửi nội dung tài liệu ra Internet.

## Tính năng chính

- Đọc PDF nguyên bản bằng Qt PDF, giữ hình, bảng và bố cục ở khung bên trái.
- Dịch từng trang theo ngữ nghĩa ở khung bên phải; giữ tiêu đề, danh sách,
  khối mã, bảng và chèn lại hình/biểu đồ không cần dịch.
- Hỗ trợ PDF, DOCX, TXT/Markdown và các định dạng ảnh phổ biến.
- OCR cục bộ cho PDF scan và bộ nhớ dịch SQLite chỉ lưu trên máy.
- macOS dùng mô hình PyTorch/MPS; Linux x86_64 dùng CTranslate2 INT8 để phù
  hợp CPU Xeon và giảm đáng kể dung lượng/RAM.

## Chạy bản macOS

```bash
cmake -S . -B build
cmake --build build -j4
open build/readDoc.app
```

Mở thẳng PDF ở chế độ song ngữ:

```bash
./build/readDoc.app/Contents/MacOS/readDoc --bilingual \
  "/Users/nhannt/Downloads/80-80020-3_REV_AB_Qualcomm_Linux_Kernel_Guide.pdf"
```

Thêm `--page 6` để mở ở một trang cụ thể.

## Chạy bản Linux x86_64

Bản Linux là một file AppImage tự chứa, tương tự cách chuyển một file DMG.
Xem hướng dẫn cài đặt, kiểm tra checksum và build lại tại
[`packaging/linux/README.md`](packaging/linux/README.md).

## Quyền riêng tư

Ứng dụng luôn bật chế độ offline cho Hugging Face/Transformers và sử dụng mô
hình đã đóng gói hoặc đã có sẵn trên máy. Nếu thiếu mô hình, ứng dụng báo lỗi
thay vì tải xuống hoặc chuyển nội dung tài liệu ra ngoài.

## Giấy phép

Mã nguồn readDoc dùng giấy phép MIT. Xem
[`packaging/linux/THIRD_PARTY_NOTICES.md`](packaging/linux/THIRD_PARTY_NOTICES.md)
trước khi phân phối gói kèm các thành phần bên thứ ba ra ngoài tổ chức.
