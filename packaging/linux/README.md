# readDoc cho Linux x86_64

## Yêu cầu

- Máy Intel/AMD x86_64; cấu hình Xeon E5-2682 v4 được hỗ trợ.
- Ubuntu 22.04 trở lên hoặc bản phân phối tương đương có glibc 2.35 trở lên.
- Không cần Python, Qt hay mô hình AI cài sẵn.

## Gửi và chạy tại công ty

Chép hai file sau sang máy Linux:

- `readDoc-1.0.0-Linux-x86_64.AppImage`
- `readDoc-1.0.0-Linux-x86_64.AppImage.sha256`

Trong thư mục chứa chúng, chạy:

```bash
sha256sum -c readDoc-1.0.0-Linux-x86_64.AppImage.sha256
chmod +x readDoc-1.0.0-Linux-x86_64.AppImage
./readDoc-1.0.0-Linux-x86_64.AppImage
```

Mở trực tiếp một PDF ở chế độ song ngữ:

```bash
./readDoc-1.0.0-Linux-x86_64.AppImage --bilingual "/duong-dan/tai-lieu.pdf"
```

Nếu máy chặn FUSE hoặc chưa có `libfuse2`, dùng chế độ tự giải nén:

```bash
./readDoc-1.0.0-Linux-x86_64.AppImage --appimage-extract-and-run
```

Tất cả mô hình, tokenizer, Qt, Python và OCR đều nằm trong AppImage. Ứng dụng
không cần mạng để đọc hoặc dịch tài liệu.

## Điều chỉnh cho dual Xeon

Mặc định mô hình dùng 16 luồng để hạn chế việc một tác vụ chạy xuyên hai NUMA
socket. Có thể thử 24 hoặc 32 luồng và giữ giá trị nhanh nhất trên máy thực:

```bash
READDOC_NMT_INTRA_THREADS=24 ./readDoc-1.0.0-Linux-x86_64.AppImage
```

Thiết lập này chỉ áp dụng lúc chạy Linux, không làm thay đổi bản macOS.

## Build lại trên macOS bằng Docker Desktop

Build script dùng Ubuntu 22.04 x86_64 làm môi trường chuẩn nên file đầu ra
không phụ thuộc thư viện trên máy Mac:

```bash
./build_linux_appimage.sh
```

Mô hình CTranslate2 INT8 phải có tại `dist/linux-x86_64/model` và tokenizer
VinAI cục bộ phải có trong cache trước khi build. Script không tải mô hình từ
mạng trong lúc ứng dụng chạy.
