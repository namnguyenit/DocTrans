# Chọn mô hình dịch có ngữ cảnh cho RTX 4070 Laptop 8 GB

Ngày đo: 20/10/2026. Cấu hình được chọn trên máy này là **Qwen3.5-4B Q6_K,
llama.cpp CUDA, 8 slot dịch liên tục**, cùng VinAI để hiện bản dịch thô sớm.

Sau kiểm thử sách 861 trang, mặc định đã đổi sang temperature 0,2,
presence penalty 1,0, bảo vệ dấu chấm mục lục và mã thiết bị; không dùng
greedy không chống lặp cho sách có mục lục dài. Số đo cũ dưới đây được giữ
làm kết quả thăm dò mô hình; xem [báo cáo PDF lớn](large-pdf-stress.md) cho
cấu hình và kiểm thử cuối.
Đây là lựa chọn tốt nhất trong những cấu hình đã thử cho dự án, không phải
khẳng định một mô hình chính xác nhất với mọi tài liệu.

## Đã so sánh những gì

| Mô hình | Cách chạy đã thử | Nhận xét từ bản dịch thực tế |
| --- | --- | --- |
| Arcee-VyLinh / Qwen2.5 3B | NF4 FP16, PyTorch CUDA | Dễ thêm diễn giải và đưa chi tiết từ ngữ cảnh vào câu cần dịch; có mẫu lẫn chữ Trung. Giữ lại để tương thích. |
| Hy-MT2-1.8B | BF16 không lượng tử, PyTorch CUDA | Phân biệt được nghĩa của port khi có ngữ cảnh; một số thuật ngữ timeout, retry và điều kiện kỹ thuật chưa đạt. Không chọn mặc định. |
| Qwen3-4B-Instruct-2507 | NF4 FP16, PyTorch CUDA, RMSNorm gộp | Ngữ cảnh giúp sửa nghĩa driver/port/charge; còn diễn đạt gượng và có mẫu dịch lock thành chìa khóa khi tham khảo bản thô. |
| **Qwen3.5-4B Q6_K** | **llama.cpp CUDA chính thức, 8 slot** | **Bản thử tự nhiên hơn, phân biệt các nghĩa đa ngành và giữ số liệu/placeholder trong các mẫu kiểm tra. Đã tích hợp.** |
| TranslateGemma-4B | Chỉ đọc tài liệu chính thức | Có hướng chuyên dịch, nhưng tải trọng số cần tài khoản chấp nhận điều kiện của Google. Chưa có số đo hay đánh giá bản dịch trên máy này. |

Nguồn của mô hình: [Qwen3.5 chính thức](https://huggingface.co/Qwen/Qwen3.5-4B),
[bản GGUF của Unsloth](https://huggingface.co/unsloth/Qwen3.5-4B-GGUF),
[Qwen3-4B](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507),
[Hy-MT2 chính thức](https://huggingface.co/tencent/Hy-MT2-1.8B),
[TranslateGemma](https://huggingface.co/google/translategemma-4b-it).
Các nhận xét trong bảng là quan sát trên mẫu của dự án, không suy ra từ điểm
benchmark do nhà phát hành công bố. GGUF được lượng tử hóa bởi Unsloth,
không phải tệp lượng tử do Qwen trực tiếp phát hành.

## Chất lượng và thời gian

Bộ kiểm tra gồm 12 câu tổng hợp: driver phần mềm/người lái xe, port mạng/cảng
biển, charge điện tích/phí dịch vụ, nhà máy, phủ định, số liệu, placeholder,
điều kiện ghi bộ nhớ và đại từ. Tất cả nội dung kiểm tra và đầu ra được lưu
trong JSON; không sử dụng tài liệu riêng của người dùng.

Một số kết quả Qwen3.5 có ngữ cảnh:

| Câu nguồn | Ngữ cảnh | Kết quả |
| --- | --- | --- |
| The driver must be restarted. | GPU và hệ điều hành | Cần khởi động lại trình điều khiển. |
| The port is blocked. | Tường lửa TCP | Cổng bị chặn. |
| The port is blocked. | Tàu hàng, luồng vào cảng | Cảng bị chặn. |
| The charge was reduced. | Tụ điện | Điện tích đã giảm. |
| The charge was reduced. | Phí dịch vụ ngân hàng | Phí đã được giảm. |
| It must release the lock before returning. | Interrupt handler, spinlock | Nó phải giải phóng khóa trước khi trả về. |

Mô hình vẫn có thể làm mất sắc thái: mẫu “does not necessarily mean” được
diễn đạt thành “không có nghĩa”, chưa giữ rõ “không nhất thiết”. Không dùng
bộ thử nhỏ này làm phần trăm chính xác chung hoặc thay cho đánh giá trên
tài liệu thực tế có bản dịch chuẩn.

- Backend CUDA trực tiếp: trung vị **2,319 giây / 12 câu có ngữ cảnh**, 3 lần
  chạy sau warm-up, không tái sử dụng KV prompt. Cả 12 đều kết thúc bằng EOS.
- Qua luồng hiệu đính thật, gồm sắp độ dài, giới hạn đầu ra và kiểm tra kết
  quả: **2,794 giây / 12 câu có ngữ cảnh**, trung vị 2 lần. Không gồm nạp
  trọng số, VinAI, OCR hoặc dựng giao diện.
- Tổng VRAM quan sát trong phép thử backend khoảng **5933 MiB**, gồm VinAI,
  llama.cpp, CUDA context và desktop. Đây là số quan sát, không phải bảo đảm
  đỉnh VRAM cho mọi đầu vào. Số bộ nhớ PyTorch trong JSON không bao gồm bộ
  nhớ do tiến trình llama.cpp giữ.

Bằng chứng cục bộ: `build/qwen35_server_context.json`,
`build/qwen35_production_context.json`, `build/qwen_context.json`,
`build/qwen_refine_context.json`, `build/hymt_context.json`,
`build/vylinh_context.json`. Các prompt/cấu hình khác nhau giữa ứng viên;
không dùng thời gian này để kết luận một kernel nhanh hơn kernel khác.

## Vì sao cấu hình này hợp với 8 GB

- Trọng số Q6_K khoảng 3,53 GB trên đĩa; không cần nạp encoder hình ảnh cho
  tác vụ dịch văn bản. OCR vẫn dùng luồng riêng của readDoc.
- Cả các lớp lặp và lớp đầu ra được đưa lên CUDA; bật Flash Attention và
  ghép yêu cầu liên tục. Khi một slot kết thúc, engine có thể nhận prompt
  tiếp theo mà không chờ các slot còn lại kết thúc.
- Mỗi slot giới hạn 2048 token, phù hợp đơn vị dịch ngắn của ứng dụng; không
  cấp phát context 262K mặc định của mô hình. Tắt sinh phần suy nghĩ để tránh
  mất thời gian/token vào lời giải thích.
- Runtime chính thức có hỗ trợ CUDA Graphs. Không khẳng định mọi phép tính
  trong mọi lượt đều dùng graph hoặc GPU phải luôn đạt 100%.
- VinAI và bộ hiệu đính chia sẻ khóa GPU để hạn chế đỉnh bộ nhớ. Không nhân
  bản mô hình theo tài liệu và không ép hai mô hình tranh GPU đồng thời.

Tài liệu engine: [llama.cpp server](https://github.com/ggml-org/llama.cpp/tree/master/tools/server).
Các mô hình 7B lượng tử có thể chạy với lô nhỏ trên 8 GB, nhưng chưa được đo
trong ứng dụng này; dư địa cho VinAI, desktop và nhiều yêu cầu sẽ ít hơn.

## Cài đặt và đổi cấu hình

Máy hiện tại đã có đầy đủ trọng số và runtime. Chỉ cần mở lại readDoc.
Trên một bản sao dự án mới, chạy bằng môi trường Python của dự án:

```powershell
.\.venv\Scripts\python.exe setup_cuda_models.py
```

Script tải GGUF Unsloth revision `e87f176479d0855a907a41277aca2f8ee7a09523`,
tokenizer Qwen revision `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a`, và runtime
Windows x64 CUDA 12.4 chính thức `b11739`. Hai gói runtime được kiểm tra SHA256.
Không cài CUDA Toolkit, thay driver hoặc gửi tài liệu đi. Toàn bộ việc tải
chỉ diễn ra khi chạy script cài đặt; daemon của ứng dụng vẫn bắt buộc offline.

Ưu tiên mặc định: Qwen3.5 GGUF khi có đủ tokenizer/runtime; nếu chưa cài thì
dùng VyLinh như trước. `READDOC_POLISH_MODEL` cho phép chọn checkpoint PyTorch
VyLinh, Qwen3 hoặc Hy-MT2 đã có trên máy. `READDOC_LLAMA_SLOTS` mặc định 8,
giới hạn 1–8, context 2048 token/slot. Cấu hình này đã đo với PDF 861 trang;
xem [kiểm thử PDF lớn](large-pdf-stress.md). Không nạp nhiều mô hình
hiệu đính cùng lúc.

Runtime Python llama-cpp có sẵn bị lỗi `0xc000001d` khi tạo context. Ứng dụng
dùng executable CUDA chính thức đặt riêng trong `tools/llama-cpp/b11739`,
không thay các DLL của môi trường Python. Server chỉ nghe 127.0.0.1, có khóa
phiên, bỏ qua proxy hệ thống và không mở giao diện web. Windows Job Object
đảm bảo đóng engine khi tiến trình Python bị Qt buộc dừng.
