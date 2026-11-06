# Kiểm thử PDF Qualcomm 861 trang và cấu hình RTX 4070 8 GB

Đo cục bộ ngày 20/10/2026, Windows, 16 GB RAM, RTX 4070 Laptop 8188 MiB,
PyTorch 2.13.0+cu126 và llama.cpp CUDA b11739. Tài liệu không được tải lên
Internet. PDF nguồn không bị sửa.

## Phạm vi và kết quả đọc tài liệu

Nguồn: `80-20659-2_REV_AG_QCS6490_Technical_Reference_Manual.pdf`, 861 trang,
8.724.736 byte, 26.780 khối chữ đưa vào luồng xử lý (không tính khối gắn cờ
watermark), khoảng 1,66 triệu ký tự. Có 441 khối trên
300 ký tự, khối dài nhất 1162 ký tự.

Trang 521 chứa mẫu nền đồ họa với ô lặp khoảng 0,05333 × 0,05333 point.
MuPDF mất nhiều phút duyệt các ô dù chúng không có chữ. Luồng cũ còn quét
font toàn bộ tài liệu nhưng không dùng kết quả trong phần trích xuất.
Bản trước sửa vẫn chưa xong sau **334,126 giây**, vượt timeout 300 giây;
đây là thời gian quan sát trước khi dừng, không phải thời gian hoàn thành.

Sau sửa, **trích xuất đủ 861 trang mất 2,311 giây**, JSON bố cục 8,27 MiB.
Riêng trang 521 lấy được 29 khối chữ trong khoảng 0,0035 giây. Chỉ các mẫu
nền rất nhỏ đã kiểm tra không có chữ, kể cả tài nguyên tham chiếu, được
làm rỗng trong bản đọc tạm trên RAM. Trường hợp không xác minh được được
để nguyên. Phần hiển thị/xuất vẫn mở PDF gốc. Đã bỏ quét font thừa và giải
mã ảnh không dùng khi lấy chữ của sách lớn.

SHA256 nguồn trước/sau:
`4012B4785F21D06F6CFCB8EFA55616BB9160521D564D83BE2B829BA17B050C33`.

## Thông số hiện dùng

| Thành phần | Thiết lập |
| --- | --- |
| Bản dịch nhanh | VinAI, CUDA FP16; giữ chia đoạn và ngân sách token |
| Dịch theo ngữ cảnh | Qwen3.5-4B Q6_K, toàn bộ lớp trên CUDA |
| Slot / context | **8 slot × 2048 token** |
| Hàng đợi gửi engine | Tối đa 24 yêu cầu, engine tự ghép liên tục |
| Đầu ra | Tối đa **384 token**, dừng sớm khi EOS |
| Lấy mẫu | **temperature 0,2; top_p 0,8; top_k 20; min_p 0** |
| Chống lặp | **presence_penalty 1,0; repeat_penalty 1,0; seed 42** |
| Cache trạng thái prompt | **cache-ram 0, ctx-checkpoints 0, cache_prompt false** |
| Kernel / nạp trọng số | Flash Attention, n_gpu_layers all, batch 512, ubatch 256 |
| Cache bản dịch | SQLite cục bộ vẫn hoạt động |

Mỗi đoạn tối đa 300 ký tự và nhận ngữ cảnh nguồn trước/sau. Khối PDF dài
được chia rồi ghép lại trong khung chữ gốc. Ô chỉ có số, địa chỉ hex, bit
range hoặc mã thiết bị được giữ nguyên; không gọi mô hình cho `QCS6490`,
`I2C`, `LPDDR4X` đứng riêng. Trong câu, mã thiết bị, biến và email được
bảo vệ khi dịch thô và kiểm tra chính xác khi nhận kết quả hiệu đính.
Kết quả bị cắt hoặc làm đổi literal được thay bằng bản thô.
Lớp giao diện giữ nguyên dấu `/`, chữ hoa/thường, dấu gạch dưới và khoảng
trắng trong mã đã được mô hình trả về; không tự viết lại các ký hiệu này.

Dấu chấm dẫn trang mục lục được đổi thành ký hiệu ngắn khi chạy mô hình,
rồi phục hồi đúng chuỗi ban đầu. Ngữ cảnh cũng bỏ chuỗi chấm trang trí.
Không đưa hàng trăm dấu chấm cho mô hình tiếp tục sinh lặp.

Cache RAM prompt của runtime trước đây cho phép tới 8192 MiB, không phù hợp
máy 16 GB chạy cùng VinAI và giao diện. Các đoạn độc lập không cần giữ lại
snapshot của những prompt cũ. Các slot CUDA và ngữ cảnh mỗi câu vẫn đầy đủ.
`READDOC_LLAMA_SLOTS=4` cho phép giảm bộ nhớ; context có thể chỉnh bằng
`READDOC_LLAMA_CONTEXT_PER_SLOT` trong 1024–4096. Mặc định cache RAM bằng 0;
`READDOC_LLAMA_CACHE_RAM_MIB` cho phép 0–1024 nếu chủ động muốn thay đổi.

## Đo tốc độ và lỗi sinh lặp

Bài thử gồm **64 đoạn đầu sách và 64 đoạn kỹ thuật lấy rải khắp tài liệu**,
để có cả mục lục lẫn thân bài. Cùng 128 nguồn, chạy CUDA tuần tự sau warm-up,
tắt cache bản dịch và cache prompt. Mỗi cấu hình dưới đây đo một lượt;
không gọi đó là trung vị hay độ chính xác chung.

| Cấu hình | Giây / 128 đoạn | Đoạn/giây | Kết thúc đầy đủ / chạy mô hình | Bị cắt |
| --- | ---: | ---: | ---: | ---: |
| Greedy, chưa xử lý dot leaders | 100,736 | 1,271 | 92/126 | 34 |
| temperature 0,7; presence 1,5 | 46,129 | 2,775 | 126/126 | 0 |
| temperature 0,2; presence 1,0 | 48,939 | 2,616 | 126/126 | 0 |
| **Cấu hình chọn + bảo vệ dot leaders/mã thiết bị** | **28,492** | **4,493** | **126/126** | **0** |

Hai yêu cầu khác không đủ điều kiện hiệu đính. Cấu hình cuối nhận 112 kết
quả, giữ bản thô cho 14 trường hợp không qua kiểm tra literal. Kiểm tra ở
lượt cuối đã chặt hơn, gồm mã thiết bị/email và số lần xuất hiện, nên không
so trực tiếp tỷ lệ nhận này như thước đo chất lượng dịch giữa các lượt.
Đã xem mẫu đầu ra để kiểm tra câu cảnh báo, phủ định, mục lục và mã thiết bị;
chưa có bản dịch chuẩn của toàn sách để chấm ngữ nghĩa.

Trên bộ mẫu này, thời gian giảm khoảng **71,7%**, thông lượng khoảng
**3,54 lần** so với cấu hình greedy chưa xử lý dấu chấm. Đây là bước hiệu
đính; không gồm VinAI, nạp trọng số, đọc PDF hoặc vẽ giao diện. Không dùng
con số này làm cam kết tốc độ cho mọi trang hoặc toàn bộ sách.

Nhóm Qwen khuyến nghị presence penalty để hạn chế lặp và lưu ý giá trị
cao có thể làm trộn ngôn ngữ. Đã thử cả thiết lập non-thinking được hãng
đề xuất và cấu hình ít ngẫu nhiên hơn; chọn cấu hình thứ hai theo kết quả
trên dữ liệu này. [Model card chính thức](https://huggingface.co/Qwen/Qwen3.5-4B#best-practices).

Nguồn: `build/qualcomm_decoding_comparison.json`,
`build/qualcomm_decoding_leaders_verified.json`. Audit có nội dung nguồn và
đầu ra chỉ lưu cục bộ trong `build/`, không đưa vào Git hoặc gửi ra ngoài.
Các bài thăm dò 4/8 slot, context 1024/2048 và RAM cache được giữ riêng ở
`build/qualcomm_model_tuning.json`, `build/qualcomm_model_tuning_low_ram.json`,
`build/qualcomm_model_tuning_verified.json`; các số đó dùng cấu hình trước
khi xử lý lỗi dấu chấm, không phải mặc định cuối.

## Kiểm tra đủ 861 trang qua giao diện và hàng đợi

Bài cấu trúc dùng peer mô hình giả để kiểm tra hết mọi đơn vị; kết quả này
không phải thời gian dịch thật bằng mô hình:

| Chỉ số | Kết quả bản cuối |
| --- | ---: |
| Trang / đơn vị văn bản sau chia | **861 / 27.301** |
| Yêu cầu gửi dịch / giữ nguyên | **22.823 / 4.478** |
| Phản hồi mất, trùng hoặc lỗi | **0** |
| Chuyển trang | 30, 250, 521, 700, 861 đều được |
| Giao diện sẵn sàng / toàn bài cấu trúc | 2,035 / 32,996 giây |
| Event loop p95 / lớn nhất | 34 / 319 ms |
| RSS cây tiến trình, không nạp mô hình | 191,8 MiB |
| Thoát | Mã 0 |

Báo cáo: `build/qualcomm_structure_final_verified.json`. So với chỉ sửa extractor,
số yêu cầu cần mô hình giảm từ 24.332 xuống 22.823, dù chia khối dài làm tăng
số đơn vị. Lượt đóng giữa chừng với 512 phản hồi giả cũng thoát mã 0.

## Lượt dịch thật kéo dài

Lượt 2048 đầu tiên phát hiện lỗi lúc thoát (`0xC0000374`) và đầu ra bị cắt;
đã ngắt tín hiệu QProcess trước khi hủy translator để tránh gọi vào giao
diện đang đóng. Có kiểm thử đóng khi còn 500 yêu cầu chờ. Bài chẩn đoán
sau đó xác định chuỗi chấm mục lục gây lặp; đã sửa theo phần trên.
Không sử dụng các lượt chẩn đoán bị dừng làm bằng chứng kiểm thử thành công.

Lượt xác nhận đã đạt ngưỡng ít nhất 2048 phản hồi và thoát sạch:

| Chỉ số | Kết quả |
| --- | ---: |
| Nguồn đã đọc | 861 trang, 27.301 đơn vị |
| Phản hồi thô / hiệu đính nhận được | **2057 / 2054** |
| Thời gian từ lúc mở file | **641,304 giây** |
| Giao diện sẵn sàng | 2,100 giây |
| Lỗi / phản hồi trùng | **0 / 0** |
| Model khi kết thúc | VinAI và Qwen3.5 đều ready |
| Thoát chương trình | **Mã 0** |
| Chuyển trang khi đang dịch | 5 lần, gồm trang 521 |
| Event loop p95 / lớn nhất | **32 / 312 ms** |
| Đỉnh tổng VRAM | **6418 MiB** |
| Đỉnh RSS cây tiến trình | **6649 MiB** |

Bộ đếm trạng thái gần cuối ghi nhận **1911/1911 lượt sinh kết thúc đầy đủ**,
không có bộ đếm truncation, OOM hoặc lỗi sinh tăng. Trong đó 1660 kết quả
được nhận, 251 được giữ bản thô vì không qua kiểm tra literal; còn có 5 cache
hit. Đây là snapshot trước khi dừng, không phải số cuối chính xác của mọi
yêu cầu. Những yêu cầu không đủ điều kiện hiệu đính nhận bản thô trực tiếp.

Bài thử dừng theo ngân sách phản hồi, `complete=false` vì chưa dịch xong cả
sách. Ba phản hồi thô cuối chưa có phản hồi hiệu đính ở thời điểm chụp số
liệu; các yêu cầu còn lại được hủy khi dừng bài thử. Không gọi việc hủy có
chủ đích này là mất phản hồi. Sau thoát không còn tiến trình llama-server
của bài thử; VRAM trở về khoảng 545 MiB trên desktop lúc kiểm tra.

RAM khả dụng toàn máy có lúc xuống 64 MiB trong lượt tải có cả build và bài
giao diện khác chạy thêm. Số này gồm tải ngoài bộ mô hình; không xem 16 GB
RAM là dư dả với mọi tổ hợp ứng dụng. Có thể đặt 4 slot nếu cần giảm bộ nhớ
khi làm việc cùng chương trình nặng. Dữ liệu PDF/hàng đợi riêng, không nạp
mô hình, chỉ khoảng 200 MiB trong bài cấu trúc.

Báo cáo giữ tại `build/qualcomm_cuda_release.json`. Các thay đổi bảo toàn
chuỗi ở giao diện được kiểm tra riêng qua transport và chạy toàn bộ hàng
đợi với peer giả sau khi rebuild; không thay thông số hay trọng số mô hình.

## Giới hạn và kiểm tra lại

Đã trích xuất và chạy hết hàng đợi 861 trang với peer giả; GPU được đo thật
trên các mẫu trải khắp sách và một lượt chạy dài trong ứng dụng. **Chưa tạo
bản dịch hoàn thiện của cả 861 trang.** Các kiểm tra literal và EOS không
chứng minh mọi câu đều đúng nghĩa, đặc biệt với thuật ngữ chuyên ngành.
Các khối được nhận diện là watermark hoặc không qua kiểm tra literal có
thể giữ nguyên tiếng Anh; cần rà soát riêng khi tạo bản dịch hoàn thiện.

Tám suite chọn theo phạm vi thay đổi đều đạt, gồm 25 ca Python cho pipeline,
transport và quản lý tiến trình CUDA, hàng đợi nhiều tài liệu, mẫu nền PDF,
chia khối, thoát giữa chừng và bảo toàn chuỗi kỹ thuật. Suite cũ `pdf_layout` dùng API chuỗi/marker
trước khi extractor chuyển sang bố cục JSON; không đưa suite đó vào tuyên
bố kiểm thử đạt. Bộ kiểm thử PDF lớn không đăng ký CTest mặc định vì file
nguồn nằm ngoài dự án.

```powershell
cmake --build build -j4
ctest --test-dir build -R 'translation_scheduler|polish_pipeline|multi_document|cuda_server|dense_pdf_patterns|pdf_translation_units|translator_shutdown|translation_literals' --output-on-failure

.venv\Scripts\python.exe -X utf8 src/Data/extract_pdf.py 'D:\Downloads\docqualcomm\nontran\80-20659-2_REV_AG_QCS6490_Technical_Reference_Manual.pdf' > build/qualcomm_layout.json

.venv\Scripts\python.exe tests/benchmark_large_pdf_app.py --input 'D:\Downloads\docqualcomm\nontran\80-20659-2_REV_AG_QCS6490_Technical_Reference_Manual.pdf' --report build/qualcomm_structure_release.json --requests 0 --seconds 240 --fake

.venv\Scripts\python.exe tests/benchmark_native_repetition.py --layout build/qualcomm_layout.json --each 64 --profiles conservative --output build/qualcomm_decoding_leaders_verified.json

.venv\Scripts\python.exe tests/benchmark_large_pdf_app.py --input 'D:\Downloads\docqualcomm\nontran\80-20659-2_REV_AG_QCS6490_Technical_Reference_Manual.pdf' --report build/qualcomm_cuda_release.json --requests 2048 --seconds 1200
```

Chạy các phép thử GPU tuần tự, đóng phiên readDoc khác đang nạp mô hình.
Không cần cài thêm CUDA Toolkit, thay driver hay chỉnh công suất GPU.

