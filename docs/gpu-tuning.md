# Tối ưu CUDA trên RTX 4070 Laptop 8 GB

## Cấu hình hiện tại sau rà soát mô hình

Sau kiểm thử PDF lớn, cấu hình cuối dùng 8 slot × 2048 token, tối đa 384
token đầu ra, tắt cache prompt RAM và context checkpoints không cần cho
các đoạn độc lập. Đã chọn temperature 0,2 và presence penalty 1,0 để tránh
lặp; dấu chấm mục lục được bảo vệ và phục hồi, mã thiết bị/email được giữ
nguyên. Bộ mẫu 128 đoạn gồm cả đầu sách và thân bài giảm từ 100,736 xuống
28,492 giây, đạt 4,493 đoạn/giây, không có lượt sinh bị cắt trong mẫu cuối.
Số này chỉ tính hiệu đính; xem [quy trình đo và giới hạn](large-pdf-stress.md).

Các bảng phía dưới ghi lại các lượt thăm dò trước khi xử lý lỗi lặp mục lục,
không đại diện toàn bộ cấu hình cuối. Báo cáo PDF lớn là nguồn số đo mới nhất.

Đã tích hợp **Qwen3.5-4B Q6_K qua llama.cpp CUDA**, 8 slot dịch liên tục,
Flash Attention, context 2048 token/slot, tắt phần suy nghĩ. VinAI vẫn trả
bản dịch thô sớm. Xem [so sánh mô hình và cài đặt](model-comparison.md).
Giao diện hiển thị tên mô hình đang dùng, không cố định nhãn VyLinh.

Mỗi yêu cầu nhận tối đa 600 ký tự ngữ cảnh từ các đoạn trước/sau của chính
tài liệu đó. Ngữ cảnh đi cùng request ID qua cả hai bước và nằm trong khóa
cache, không lấy từ thứ tự xử lý của hàng đợi nhiều tài liệu. Các số liệu,
định danh và placeholder được kiểm tra trước khi nhận kết quả; câu bị cắt
hoặc làm hỏng các giá trị này giữ bản thô. Kiểm tra này không phát hiện được
tất cả lỗi ngữ nghĩa.

Worker hiện lấy tối đa 24 yêu cầu, ngân sách 12288 token. Với GGUF, các slot
CUDA được điền tiếp ngay khi có câu kết thúc. Với PyTorch, các prompt vẫn
được ghép thành lô có giới hạn padding. Mô hình dùng chung khóa GPU với
VinAI, không cần tạo thêm bản sao theo số tài liệu.

Với các checkpoint Qwen2/Qwen3 PyTorch, đã thay RMSNorm thành toán tử CUDA
gộp có sẵn của PyTorch. Trên cùng VyLinh, 3 lần đo sau warm-up:

| Khối lượng | Trước kernel gộp | Sau kernel gộp |
| --- | ---: | ---: |
| 8 câu ngắn | 1,814 giây | 1,528 giây |
| 8 đoạn, mỗi đoạn 4 câu | 5,476 giây | 4,525 giây |

Thời gian giảm khoảng 16–17%; đầu ra trong hai bộ mẫu giống nhau trước/sau.
Số đo: `build/vylinh_fused_verified.json`. Có thể tắt bằng
`READDOC_FUSED_RMSNORM=0`. Tối ưu này chỉ áp dụng các lớp RMSNorm Qwen2/Qwen3
đã đối chiếu công thức, không thay tùy ý các kiến trúc khác.

Trên Qwen3 NF4 với 24 câu ngắn có ngữ cảnh, tăng batch từ 8 lên 24 giảm
thời gian 5,153 xuống 3,132 giây, thông lượng tăng khoảng 65%; đỉnh allocator
PyTorch 4433 MiB, reserve 4736 MiB. Đây là số đo PyTorch, không gồm desktop
hay CUDA context. Không dùng các lượt đoạn dài của phép thử này làm số đo
đối chiếu vì một phần thời gian có tiến trình thử khác cùng dùng GPU.

Bài thử ngắn trước đây (12 câu) chưa thể hiện rõ lợi ích của 8 slot. Đo lại
trên 128 đoạn lấy rải khắp tài liệu Qualcomm 861 trang, mỗi cấu hình hai
lượt không dùng cache, cho kết quả:

| Slot × context/slot | Trung vị / 128 đoạn | Đoạn/giây | Đỉnh tổng VRAM |
| --- | ---: | ---: | ---: |
| 4 × 2048 | 50,118 giây | 2,554 | 6384 MiB |
| 8 × 1024 | 44,766 giây | 2,859 | 6600 MiB |
| **8 × 2048** | **43,612 giây** | **2,935** | **6856 MiB** |

Chọn **8 × 2048**, tăng thông lượng hiệu đính khoảng 14,9% so với 4 slot,
giữ dư địa ngữ cảnh. Cả ba cấu hình đều có 254/254 phản hồi mô hình kết thúc
đầy đủ qua hai lượt; hai yêu cầu còn lại bị bỏ qua theo tiêu chí đủ điều
kiện hiệu đính. Không có lỗi hết bộ nhớ hoặc từ chối vì thiếu context.
Ở cấu hình được chọn, 21/254 phản hồi không giữ nguyên số/định danh nên
được thay bằng bản dịch thô; đây không phải phép đo độ chính xác ngữ nghĩa.

Đây là thời gian bước hiệu đính sau warm-up; không gồm đọc PDF, nạp mô hình,
VinAI hoặc vẽ giao diện. Xem [kiểm thử PDF lớn](large-pdf-stress.md) và
`build/qualcomm_model_tuning.json`. Có thể đặt `READDOC_LLAMA_SLOTS=4` để
giảm bộ nhớ khi chạy cùng ứng dụng khác. `READDOC_LLAMA_CONTEXT_PER_SLOT`
mặc định 2048, cho phép 1024–4096; tăng context làm tăng bộ nhớ và cần đo lại.

Engine hiện còn tắt cache snapshot prompt trong RAM (`--cache-ram 0`),
thay cho giới hạn 8192 MiB mặc định của runtime, để phù hợp máy 16 GB RAM.
SQLite lưu bản dịch và ngữ cảnh của từng yêu cầu vẫn hoạt động. Các số đo
ở bảng trên dùng giới hạn cache RAM cũ; kết quả sau điều chỉnh RAM và bài
chạy ứng dụng thật được ghi riêng trong [kiểm thử PDF lớn](large-pdf-stress.md).

Máy đã dùng CUDA runtime: PyTorch `2.13.0+cu126`; engine độc lập dùng runtime
CUDA 12.4 đi kèm bản phát hành chính thức. Profiler PyTorch xác nhận kernel
FP16/BF16 Tensor Core, bitsandbytes NF4 và SDPA memory-efficient attention;
không phải mọi bước NF4 đều dùng Tensor Core. Không tìm thấy `nvcc` trên
PATH; chương trình không cần biên dịch kernel riêng để sử dụng các runtime
này. Cài thêm CUDA Toolkit không tự tăng tốc suy luận.

Tham chiếu: [PyTorch CUDA semantics](https://docs.pytorch.org/docs/stable/notes/cuda.html),
[RMSNorm](https://docs.pytorch.org/docs/2.13/generated/torch.nn.functional.rms_norm.html).

## Lịch sử tối ưu VyLinh ban đầu

Luồng nhiều tài liệu và hàng đợi dùng chung được mô tả riêng tại
[Dịch nhiều tài liệu](multi-document.md).

Rà soát ngày 20/10/2026 trên GPU thực tế NVIDIA GeForce RTX 4070 Laptop,
8188 MiB VRAM. Môi trường đang dùng: Python 3.13, PyTorch 2.13.0+cu126,
Transformers 5.15.0, bitsandbytes 0.50.1, Accelerate 1.14.0.

## Nút thắt tìm thấy

- VyLinh là mô hình Qwen2.5 3B, 36 lớp, 16 attention heads, 2 KV heads.
  Ứng dụng dùng thư mục checkpoint và nén NF4 4-bit khi nạp; file GGUF Q6_K
  có sẵn không được dùng bởi nhánh hiệu đính hiện tại.
- Worker cũ lấy tối đa 2 câu nhưng `polish_batch` vẫn gọi `generate` từng câu.
  GPU phải chạy nhiều lượt nhỏ, đọc lại trọng số cho từng chuỗi sinh token.
- Bộ đếm dọn CUDA bắt đầu lại từ 0 mỗi lần gọi hàm, nên
  `torch.cuda.empty_cache()` thực tế được gọi gần như mỗi lượt hiệu đính.
- Ngưỡng bỏ hiệu đính ở 90% chỉ dựa trên bộ nhớ PyTorch đã cấp phát, không phản
  ánh tổng VRAM hoặc bộ nhớ đệm. Ngưỡng này cũng không thử giảm batch.
- VinAI và VyLinh có thể cấp phát bộ nhớ sinh token đồng thời trên cùng GPU.
- Giới hạn đầu ra tính theo số từ tiếng Việt, dù mô hình sinh theo token.
- Bộ lọc `"void " in text` nhận nhầm cả từ "avoid", khiến câu văn bình thường
  hoặc đoạn có từ này bị bỏ qua hiệu đính. Đã thêm ranh giới từ và kiểm thử.

## Cấu hình trong đợt tối ưu ban đầu

| Thông số | Giá trị ở đợt đầu |
| --- | --- |
| `READDOC_POLISH_BATCH_SIZE` | 8 câu tối đa mỗi lô |
| `READDOC_POLISH_TOKEN_BUDGET` | 4096 token đệm, gồm prompt và đầu ra dự kiến |
| `READDOC_POLISH_MAX_NEW_TOKENS` | 384 token đầu ra tối đa mỗi câu |
| `READDOC_POLISH_METRICS` | 0; đặt 1 để ghi thời gian/lô và độ dài hàng đợi vào stderr |
| Lượng tử hóa | NF4 4-bit, double quantization |
| Kiểu tính toán và trọng số không lượng tử | FP16 |
| Attention | PyTorch SDPA |
| Padding | Trái, với attention mask |
| Sinh văn bản | Greedy, KV cache bật |

Mỗi câu vẫn có prompt riêng. Sắp các câu có độ dài gần nhau rồi sinh trong
cùng một lần gọi mô hình; không gộp nội dung nhiều câu vào một prompt.
Giới hạn token tự giảm số câu mỗi lô đối với đoạn dài. Không chờ đủ 8 câu
mới chạy: nếu hàng đợi đang ít việc thì xử lý ngay số câu sẵn có.

Nếu CUDA báo hết bộ nhớ, giải phóng các tensor của lượt lỗi rồi chia đôi lô
để thử lại. Chỉ khi một câu riêng lẻ vẫn không chạy được mới giữ bản dịch thô.
Không dọn cache CUDA trong đường chạy bình thường. VinAI và VyLinh dùng khóa
chung cho các lượt sinh trên GPU để hạn chế đỉnh bộ nhớ chồng nhau.

Giới hạn đầu ra dựa trên token của bản dịch thô. Nếu chưa có EOS khi hết giới
hạn, giữ bản dịch thô thay vì hiển thị câu hiệu đính bị cắt ngang. Đoạn vượt
ngân sách của cả một lô đơn cũng giữ bản dịch thô, không cắt mất đầu vào.

Khóa nạp mô hình ngăn việc bấm khởi động lại tạo nhiều bản sao VyLinh hoặc
nhiều worker cùng lúc. Khóa cache hiệu đính mới phân biệt cả bản dịch thô,
nguồn tiếng Anh và đường dẫn mô hình.

## Kết quả đo

Cả VinAI và VyLinh nằm trên GPU; warm-up trước khi đo; vô hiệu hóa bộ nhớ dịch;
mỗi cấu hình chạy 3 lần và lấy trung vị. Bản đối chiếu cũ và mới dùng chung
đối tượng mô hình đã nạp để tách ảnh hưởng của cách nạp trọng số. Dữ liệu là
8 câu kỹ thuật tổng hợp,
không sử dụng tài liệu cá nhân. Thời gian dưới đây chỉ tính bước hiệu đính,
không gồm nạp mô hình, OCR, trích xuất PDF hoặc vẽ giao diện.

| Cấu hình / khối lượng | Thời gian | Đơn vị/giây |
| --- | ---: | ---: |
| Mã cũ, 8 câu ngắn, sinh từng câu | 9,456 giây | 0,846 |
| Mã mới, 8 câu ngắn, tối đa 8 câu/lô | 1,717 giây | 4,659 |
| Mã mới, 8 khối dài, mỗi khối gồm 4 câu | 4,357 giây | 1,836 |

Trên mẫu ngắn này, mặc định mới tăng thông lượng khoảng **5,5 lần** so với mã
cũ. Cả 8 đầu vào đều thực sự được đưa vào mô hình trong từng lần đo. Mã cũ có
7/8 phản hồi kết thúc bằng EOS ở mỗi lần chạy; mã mới đạt 8/8 trên cả hai mẫu
ngắn và dài. Không có OOM trong các lượt đo thực tế.

PyTorch ghi nhận đỉnh bộ nhớ cấp phát khoảng 3578 MiB ở mẫu ngắn và 3656 MiB
ở mẫu dài; đỉnh bộ nhớ giữ trong allocator lần lượt là 3726 và 3768 MiB.
Số này gồm cả hai mô hình nhưng
không gồm desktop, CUDA context và các ứng dụng khác.

Đây không phải bảo đảm tăng 5,5 lần cho mọi PDF. Hiệu quả phụ thuộc chiều dài
đoạn, số công việc chờ, số token đầu ra và tải GPU khác. Chạy lô tối ưu thông
lượng; không có nghĩa độ trễ của một câu đơn giảm cùng tỷ lệ. Ngân sách đầu ra
mới khác mã cũ để tránh cắt câu, nên nội dung sinh có thể khác; benchmark không
thay thế đánh giá chất lượng dịch. VyLinh vẫn có thể diễn giải thêm dù prompt
yêu cầu giữ nguyên ý; cần kiểm tra các tài liệu đòi hỏi độ chính xác cao.

Kiểm tra tích hợp bằng worker thật nhận đủ 8 phản hồi VinAI và 8 phản hồi
VyLinh, không có lỗi, trong khoảng 1,969 giây trên mẫu thử sau warm-up.
9 kiểm thử riêng cho batching, cache, chia lô khi OOM giả lập, đầu ra bị cắt,
khôi phục worker và tránh nạp trùng mô hình đều đạt. Các lỗi kiểm thử bố cục
PDF đã phát hiện trước đợt tối ưu này chưa được sửa trong phạm vi thay đổi.

Số đo chi tiết và nội dung đầu ra của phiên kiểm tra này nằm tại
`build/polish_benchmark_verified.json`.

## Chạy và kiểm tra lại

Mở lại `build/readDoc.exe` sau khi đồng bộ resource. Mô hình được nạp lại khi
ứng dụng khởi động; không cần thay trọng số hoặc tải thư viện mới trong môi
trường đã kiểm tra này. CMake target `sync_app_resources` sao chép mã daemon
từ `src/System` sang `build/resources`.

```powershell
.\.venv\Scripts\python.exe -B tests/test_polish_pipeline.py
$env:READDOC_POLISH_MODEL = "$PWD\models\polish\Arcee-VyLinh"
.\.venv\Scripts\python.exe -B tests/benchmark_polish.py --batch-sizes 2,4,8 --include-long --pipeline --output build/polish_benchmark.json
```

Đóng các phiên readDoc khác trước khi benchmark để không nạp thêm một cặp mô
hình vào cùng 8 GB VRAM. Kết quả JSON chứa thời gian từng lần chạy, đỉnh bộ nhớ
và nội dung đầu ra để đối chiếu. Có thể chọn `--long-samples` để chỉ đo các
khối gồm bốn câu, hoặc `--daemon` để đo bản mã cũ đã lưu riêng.
Thêm `--compare-daemon build/local_nmt_daemon_before_gpu_tuning.py` để so cách
xử lý cũ và mới trên cùng mô hình đã nạp; bản mã cũ này đã được lưu trong
thư mục build của máy dùng để kiểm tra, không nằm trong Git.

Nếu cần giảm VRAM trong môi trường có nhiều ứng dụng GPU:

```powershell
$env:READDOC_POLISH_BATCH_SIZE = "4"
$env:READDOC_POLISH_TOKEN_BUDGET = "1536"
.\build\readDoc.exe
```

Không tự thay giới hạn công suất, xung GPU, trình điều khiển hoặc chế độ nguồn
của máy. GPU utilization không cần luôn đạt 100% để có thông lượng tốt; phần
sinh tuần tự còn phụ thuộc băng thông bộ nhớ và chi phí khởi chạy kernel.

## Tài liệu đối chiếu

- [Transformers 5.15: batched text generation và left padding](https://huggingface.co/docs/transformers/v5.15.0/en/llm_tutorial)
- [Transformers: attention backends, quantization và KV cache](https://huggingface.co/docs/transformers/main/optimization_overview)
