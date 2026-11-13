# Benchmark: 20 câu hỏi (15 dev / 5 test)

File: [questions.jsonl](questions.jsonl). Kiểm chứng bằng `python scripts/verify_benchmark.py` (chạy từ `starter/`), kết quả nằm ở [../results/benchmark_verification.json](../results/benchmark_verification.json).

## Trường dữ liệu
`id`, `split`, `type`, `question`, `expected_answer`, `gold_source_id`, `gold_page` (list, chấp nhận bất kỳ trang nào trong list), `article` (để phân tích lỗi), `evidence_quote`, `filter` (null hoặc dict), và `filter_note`/`gold_note` khi cần giải thích.

## Phân bố

| Loại | Dev | Test |
|---|---|---|
| truc_tiep (hỏi trực tiếp) | q01, q05, q08, q11 | q16 |
| dien_dat_lai (diễn đạt lại, dùng từ đời thường) | q03, q06, q09, q13 | q18 |
| dieu_kien (điều kiện / ngoại lệ) | q02, q04, q07, q10, q12 | q17 |
| metadata (có filter) | q14, q15 | q19, q20 |

- Theo nguồn: BLLĐ có 12 câu (dev 10, test 2), BHXH có 8 câu (dev 5, test 3).
- 4 câu có filter (≥ 3), trong đó 2 câu ở test (≥ 1).
- Câu filter được chọn ở những chỗ hai đoạn văn có nội dung gần giống nhau, để không có filter thì dễ lấy nhầm trang:
  - q14: thai sản ở BLLĐ Điều 139 so với BHXH Điều 53.
  - q15: lương hưu BHXH bắt buộc Điều 66 so với BHXH tự nguyện Điều 99.
  - q19: trợ cấp thai sản Điều 95 so với Điều 59.
  - q20: mai táng Điều 109 so với Điều 85.
- Giá trị filter lấy từ chính câu hỏi ("Theo Bộ luật Lao động", "bảo hiểm xã hội tự nguyện/bắt buộc"). Đây là input do người dùng cung cấp trước khi truy xuất, không lấy từ gold.

## Cách chia và kiểm chứng
- Split được chốt **trước khi chạy bất kỳ thử nghiệm nào** (ngày 2026-11-13). Không sửa test sau khi xem kết quả.
- Test được rải trên cả 2 luật và cả 4 loại câu để đại diện cho dev.
- Evidence được kiểm tra tự động trên text đã trích từ PDF: 18/20 câu khớp nguyên văn sau khi chuẩn hóa khoảng trắng. 2 câu (q09, q16) chỉ khớp khi bỏ hết khoảng trắng, vì PDF của BLLĐ tách sai chữ (ví dụ "lao đ ộng"). Câu trích được ghi theo đúng chính tả của văn bản.
- Script cũng tìm các trang khác chứa cùng evidence. Nhờ đó q18 được bổ sung gold thay thế (p40, p53).

## Nguy cơ rò rỉ và thiên lệch
- Không chia được theo tài liệu (chỉ có 2 luật), nên dev và test cùng nguồn. q15 (dev) và q19, q20 (test) cùng khai thác cấu trúc song song Chương V/VI, nên kết quả filter trên dev có thể lạc quan so với dữ liệu khác.
- Câu hỏi do tác giả viết sau khi đọc văn bản, nên có thể dùng từ trùng với văn bản nhiều hơn câu hỏi của người dùng thật.
- Câu hỏi được soạn với sự hỗ trợ của AI (Claude). Evidence và trang đã được kiểm chứng bằng script; tác giả cần tự đọc lại từng câu trên PDF.

## Tiêu chí chọn chiến lược (chốt trước khi xem test)
1. Evidence Hit@3 trên **dev** cao nhất.
2. Nếu hòa (chênh ≤ 1 câu): chọn Hit@1 dev cao hơn.
3. Nếu vẫn hòa: chọn số chunk ít hơn / thời gian ingest thấp hơn.

Sau khi chọn trên dev, cố định cấu hình rồi mới chạy test. Grounding và coherence chấm thủ công trên test được dùng để phân tích, không dùng để chọn lại.
