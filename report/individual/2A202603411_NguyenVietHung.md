# Báo cáo cá nhân — Day 6

**Học viên:** Nguyễn Việt Hưng · **MSSV:** 2A202603411 ·

## Dữ liệu và pipeline

- **Chủ đề, nguồn/quyền, số trang và quy tắc tính trang:**
  - Chủ đề là pháp luật lao động và bảo hiểm xã hội Việt Nam. Corpus gồm 2 văn bản:
    - `blld-vbhn125-2025`: Văn bản hợp nhất 125/VBHN-VPQH (2025) của Bộ luật Lao động 45/2019/QH14, đã gồm sửa đổi theo Luật 71/2025/QH15. PDF tải từ static.luatvietnam.vn.
    - `luat-bhxh-41-2024`: Luật Bảo hiểm xã hội 41/2024/QH15, bản gốc. PDF tải từ Cổng thông tin điện tử BHXH Việt Nam (baohiemxahoi.gov.vn).
    - Ngày tải: 2026-11-13. Mã sha256 của từng file có trong manifest.
  - Quyền sử dụng: văn bản quy phạm pháp luật không thuộc đối tượng bảo hộ quyền tác giả (Điều 15 khoản 2 Luật Sở hữu trí tuệ), nên PDF được đưa vào repo.
  - Đơn vị đếm là 1 trang PDF vật lý. Chỉ tính trang có nội dung điều luật. Loại trang chỉ có nơi nhận/chữ ký/xác thực, và trang không trích được text đọc được.
  - Kết quả: BLLĐ tính **85/86** trang (loại trang 86: trang xác thực, text lỗi font hoàn toàn với vi_ratio = 0,00). BHXH tính **68/68** trang. **Tổng 153 trang nội dung, 372.506 ký tự** sau chuẩn hóa.
  - Chi tiết: [data/sources.json](../../data/sources.json), [data/manifest.json](../../data/manifest.json) (danh sách `page_id`, số ký tự và chương từng trang), thống kê từng trang ở [results/inspect_*.txt](../../results/).
- **Chuẩn hóa, lỗi và giới hạn:**
  - Đọc PDF bằng `pypdf` 6.21.4. Chuẩn hóa Unicode NFC, bỏ ký tự NBSP/soft hyphen/BOM, gộp khoảng trắng nhưng **giữ xuống dòng** (để nhận diện Chương/Điều/khoản), và bỏ dòng chỉ chứa số trang in.
  - Mỗi trang được ghi `chars`, `vi_ratio` (tỉ lệ ký tự có dấu, dùng để phát hiện lỗi font), cờ `empty`/`unreadable` và lỗi trích xuất nếu có. Log ở [results/ingest_log.json](../../results/ingest_log.json): không trang nào được tính bị gắn cờ.
  - **Giới hạn chính:** text layer của PDF BLLĐ tách sai khoảng trắng bên trong từ (ví dụ "lao đ ộng", "c ủa"). Script inspect đếm được khoảng 280 lần trên các mẫu kiểm tra. Lỗi này không sửa được một cách đáng tin cậy, nên pipeline giữ nguyên text và so khớp evidence sau khi bỏ toàn bộ khoảng trắng. Lỗi vẫn ảnh hưởng tới embedding và tới khả năng đọc của chunk.
  - Trang 86 của BLLĐ chưa được OCR. Văn bản hợp nhất có chú thích cuối trang nằm lẫn vào text.
  - Hai văn bản ở hai trạng thái khác nhau: BLLĐ là bản hợp nhất đã gồm sửa đổi, còn BHXH là bản gốc chưa gồm các luật sửa đổi năm 2025.
- **Embedding model/provider/version/số chiều, vector store/version, metric, lệnh chạy và chi phí:**
  - **Embedding:** `intfloat/multilingual-e5-small` chạy local qua sentence-transformers 6.3.0 (torch 2.15.0 bản CPU), snapshot HF `614241f6…`, **384 chiều**, max_seq_length 512. Thêm tiền tố `query: `/`passage: ` theo model card và chuẩn hóa L2. Không chunk nào vượt 512 token (lớn nhất 258 token).
  - **Vector store:** PostgreSQL 16.16 + pgvector 0.8.7 (Docker `pgvector/pgvector:0.8.7-pg16`), bảng `law_chunks`.
  - **Metric:** khoảng cách cosine `<=>`, tìm kiếm **exact** (sequential scan, không index ANN).
  - **Chi phí:** 0 USD (không dùng API trả phí).
  - Lệnh chạy, từ thư mục `starter/`:
    - `python scripts/build_manifest.py`
    - `python scripts/verify_benchmark.py`
    - `python -m src.run ingest`
    - `python -m src.run eval --split dev`
    - `python -m src.run samples`
    - `python -m src.run eval --split test --frozen`
    - `python scripts/summarize_labels.py`
  - Version đầy đủ ở [results/run_info.json](../../results/run_info.json).
- **Metadata bắt buộc, trường lọc bổ sung, nguồn giá trị và lý do chọn:**
  - Mỗi chunk có `document_id`, `source` (đường dẫn PDF), `page` (trang PDF vật lý), cùng `char_start`/`char_end` trong trang và `content_hash`.
  - Hai trường dùng để lọc:
    - `law_name` (text, 2 giá trị: `bo-luat-lao-dong` | `luat-bao-hiem-xa-hoi`), lấy từ tiêu đề văn bản.
    - `chapters` (text[], số chương La Mã), lấy từ dòng tiêu đề "Chương …" trong PDF. Một chunk nằm giữa hai chương mang cả hai giá trị.
  - Trường thêm để truy vết: `articles` (ví dụ "Điều 70").
  - Lý do chọn: hai luật có nhiều đoạn gần giống nhau (thai sản, lương hưu, mai táng), và trong Luật BHXH, Chương V (bắt buộc) và Chương VI (tự nguyện) có cấu trúc song song. Vì vậy filter theo luật và chương giúp phân biệt phạm vi khi người hỏi đã nêu rõ phạm vi đó.

## Cấu hình và benchmark

- **A / B / C (tham số cụ thể, khác biệt duy nhất B–C):**
  - **A:** `fixed_size`, 500 ký tự, overlap 50. Ranh giới lùi tối đa 20 ký tự về khoảng trắng gần nhất để không cắt đôi từ. Chunk nằm trong 1 trang. Không lọc.
  - **B:** `by_paragraph`, tối đa 800 ký tự.
    - Đoạn được xác định bởi Chương/Mục/Điều/khoản "1."/điểm "a)"; các dòng bị ngắt do PDF được gộp lại.
    - Luôn mở chunk mới ở mỗi Điều.
    - Chunk viết tiếp một Điều được thêm prefix "Điều X. … (tiếp)".
    - Bỏ các mảnh chỉ có tiêu đề ở cuối trang, vì tiêu đề đó đã được lặp lại làm prefix ở trang sau.
    - Không lọc.
  - **C:** dùng **đúng chunk và index của B**, chỉ thêm điều kiện SQL lọc theo `law_name`/`chapter` khi câu hỏi có filter. Câu không có filter thì C chạy không lọc.
  - Cả ba dùng cùng corpus, cùng model, cùng store, cùng metric và cùng top-3.
  - Độ dài chunk: A có 884 chunk (trung bình 460 ký tự, 123 token); B có 744 chunk (trung bình 531 ký tự, 143 token). Kích thước hai bên tương đương, nên so sánh A–B chủ yếu phản ánh **cách cắt ranh giới**.
  - Cấu hình nằm trong `STRATEGIES` của [starter/src/run.py](../../starter/src/run.py) và [results/run_info.json](../../results/run_info.json).
- **≥20 câu: phân chia ≥15 dev / ≥5 test, câu metadata filter và cách kiểm chứng evidence:**
  - Bộ câu hỏi có **20 câu: 15 dev, 5 test**, chốt split trước khi chạy thử. File: [benchmark/questions.jsonl](../../benchmark/questions.jsonl), mô tả ở [benchmark/README.md](../../benchmark/README.md).
  - Phân bố loại câu:
    - Trực tiếp: 5 câu
    - Diễn đạt lại: 5 câu
    - Điều kiện/ngoại lệ: 6 câu
    - Có filter: 4 câu (q14, q15 thuộc dev; q19, q20 thuộc test)
  - Giá trị filter lấy từ chính câu hỏi ("Theo Bộ luật Lao động", "bảo hiểm xã hội tự nguyện/bắt buộc"), không lấy từ gold.
  - [starter/scripts/verify_benchmark.py](../../starter/scripts/verify_benchmark.py) kiểm tra evidence nằm ở gold page:
    - 18/20 câu khớp nguyên văn sau chuẩn hóa khoảng trắng.
    - 2/20 câu (q09, q16) chỉ khớp khi bỏ hết khoảng trắng, do lỗi tách chữ.
    - Script cũng tìm các trang khác chứa cùng evidence. Nhờ đó q18 được bổ sung gold thay thế p40 và p53 trước khi chạy thử.
  - Kết quả kiểm tra: [results/benchmark_verification.json](../../results/benchmark_verification.json).
- **Tiêu chí chọn chiến lược đã chốt trước khi xem test:**
  1. Evidence Hit@3 trên dev cao nhất.
  2. Nếu hòa (chênh ≤ 1 câu): chọn Hit@1 dev cao hơn.
  3. Nếu vẫn hòa: chọn số chunk ít hơn / thời gian thấp hơn.

  Sau đó cố định cấu hình rồi mới chạy test. Lệnh `eval --split test` bị chặn trong code nếu không có cờ `--frozen`.

## Kết quả

Thời gian ingest là lần nạp đầu, gồm chia chunk, embedding trên CPU và ghi vào pgvector. Thời gian đọc và chuẩn hóa 153 trang là 7,7 giây và dùng chung cho cả ba strategy. Thời gian truy xuất là tổng cho cả split, gồm search và chấm điểm, không gồm embedding câu hỏi. C dùng lại index của B nên không tốn thêm thời gian ingest.

| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian | Chi phí |
|---|---|---|---|---|---|---|
| A | dev | 5/15 | 10/15 | 884 | ingest 16,0 s; truy xuất 0,49 s | 0 |
| B | dev | 10/15 | 15/15 | 744 | ingest 17,3 s; truy xuất 0,42 s | 0 |
| C | dev | 11/15 | 15/15 | 744 (index B) | truy xuất 0,36 s | 0 |
| A | test | 2/5 | 5/5 | 884 | truy xuất 0,21 s | 0 |
| B | test | 3/5 | 4/5 | 744 | truy xuất 0,19 s | 0 |
| C | test | 3/5 | 4/5 | 744 (index B) | truy xuất 0,20 s | 0 |

**Nạp lại:**
- Chạy ingest lần 2 với cùng dữ liệu: 0 chunk phải embed lại, A vẫn 884 dòng, B vẫn 744 dòng, không trùng `chunk_id` (lịch sử ở [results/ingest_stats.json](../../results/ingest_stats.json)).
- Thử mô phỏng tài liệu thay đổi trên một strategy tạm (đã xóa sau khi thử): chỉ embed lại 1 chunk bị sửa và xóa 2 chunk không còn trong tài liệu.

| Strategy | Coherence trung bình /2 (n) | Metadata đủ và đúng (n/N) | Filter tuân thủ (n/N hoặc N/A) | Grounding 0/1/2 (số câu) và trung bình /2 |
|---|---|---|---|---|
| A | 0,7 (n=10) | 15/15 | test 1/2 (dev 0/2) | 0 / 1 / 4 → 1,8 |
| B | 1,8 (n=10) | 15/15 | test 0/2 (dev 0/2) | 1 / 0 / 4 → 1,6 |
| C | 1,8 (n=10; cùng chunk B) | 15/15 | test 2/2 (dev 2/2) | 1 / 0 / 4 → 1,6 |

"Filter tuân thủ" nghĩa là cả 3 kết quả trong top-3 đều khớp filter của câu hỏi. Với A và B, chỉ số này được đo dù hai strategy đó không áp dụng filter, để thấy khi không lọc thì kết quả lẫn phạm vi khác đến mức nào.

**Đường dẫn trace, nhãn thủ công và cách chọn mẫu:**
- Trace top-3 đầy đủ (câu hỏi, chunk ID, text, score, metadata, cờ hit): [results/traces/](../../results/traces/) (`dev_A/B/C.jsonl`, `test_A/B/C.jsonl`).
- Chỉ số: [results/summary_dev.json](../../results/summary_dev.json), [results/summary_test.json](../../results/summary_test.json).
- Toàn bộ chunk: [results/chunks/](../../results/chunks/).
- Nhãn thủ công: [results/manual/](../../results/manual/) (`coherence_labels.csv`, `grounding_labels.csv`, `metadata_audit.csv`), tổng hợp ở [results/manual_summary.json](../../results/manual_summary.json).
- Cách chọn mẫu và quy ước chấm: [results/manual/README.md](../../results/manual/README.md).
  - **Coherence:** 10 trang cách đều trong 153 trang, lấy vị trí giữa trang. Mẫu được chọn tự động trước khi chấm.
  - **Grounding và metadata:** 5 câu test × top-3 × 3 strategy.
  - Metadata được đối chiếu bằng một script độc lập: tự trích text thô từ PDF và xác định lại trang/Chương/Điều. Script đã được thử với dữ liệu sai cố ý và phát hiện được lỗi.

## Phân tích và kết luận

- **So sánh A–B và B–C; 2 ví dụ sai có ID câu và nguồn:**
  - **A → B (đổi cách chunk):**
    - Trên dev, Hit@3 tăng từ 10/15 lên 15/15 và Hit@1 từ 5/15 lên 10/15. Coherence tăng từ 0,7 lên 1,8.
    - A thường **lấy đúng trang nhưng chunk không chứa trọn evidence**: Gold page trong top-3 của A đạt 14/15, nhưng Hit@3 chỉ 10/15. Ở q10 và q14, evidence bị cắt đôi qua hai chunk.
    - Coherence của A bị 0 điểm khi chunk bắt đầu giữa câu và mất chủ thể (ví dụ pos04, BLLĐ p52, Điều 137 khoản 2).
    - Trên test, B không còn hơn A: Hit@3 của A là 5/5 so với B 4/5, grounding A 1,8 so với B 1,6. Với 5 câu, chênh lệch này chỉ tương ứng 1 câu.
  - **B → C (chỉ thêm filter):**
    - Hit@3 không đổi (dev 15/15, test 4/5). Hit@1 dev tăng từ 10/15 lên 11/15.
    - Tuân thủ filter tăng từ 0/2 lên 2/2 ở cả dev và test. Ví dụ ở q20 (test), C loại được Điều 85 (BHXH bắt buộc, p45–46) khỏi top-3, còn B vẫn để Điều 85 ở hạng 2 và 3.
  - **Ví dụ sai 1, q19 (test, `luat-bhxh-41-2024` p50, Điều 95), B và C trượt Hit@3, grounding 0:**
    - Chunk chứa "Mức trợ cấp thai sản là 2.000.000 đồng" không vào top-3.
    - Top-3 của B là điều kiện hưởng (Điều 94) và Điều 58 của BHXH bắt buộc (02 lần mức tham chiếu), là thông tin dễ dẫn tới câu trả lời sai.
    - C đã loại được Điều 58 nhờ filter Chương VI, nhưng vẫn xếp ba khoản của Điều 94 lên trên Điều 95.
    - A lại trúng (hạng 2), vì một cửa sổ fixed-size gộp cả cuối Điều 94 và Điều 95.
    - Nhận xét: filter chỉ thu hẹp phạm vi, không sửa được thứ hạng trong cùng một chương. Các chunk ngắn theo từng khoản có thể "thắng" chunk chứa đáp án.
  - **Ví dụ sai 2, q18 (test, `luat-bhxh-41-2024` p39, Điều 70), A trúng Hit@3 nhưng grounding chỉ 1:**
    - Cả 3 chunk của A có điểm "ung thư, bại liệt, xơ gan mất bù, lao nặng, AIDS", nhưng điều kiện đầu khoản "đã chấm dứt tham gia bảo hiểm xã hội mà có đề nghị" bị cắt ở ranh giới chunk.
    - B có chunk chứa trọn đầu Điều 70, nên grounding đạt 2.
    - Nhận xét: Hit@3 tự động chưa đủ để kết luận về grounding.
  - **Ví dụ thêm, q13 (dev, BHXH p29):** cả 3 kết quả của A đều đúng trang 29 nhưng không chunk nào chứa trọn câu "07 ngày làm việc khi vợ sinh con phải phẫu thuật…".
- **Chiến lược chọn, đánh đổi, điều kiện áp dụng:**
  - Theo tiêu chí đã chốt, B và C hòa ở Hit@3 dev (15/15), C có Hit@1 cao hơn (11 so với 10), nên **chọn C**.
  - **Ưu điểm của C:** chunk trọn Điều/khoản, dễ đọc (coherence 1,8), có prefix tên Điều để truy nguồn, và trả về đúng phạm vi khi người dùng nêu luật/chương (tuân thủ filter 2/2). Ít chunk hơn A (744 so với 884).
  - **Đánh đổi:**
    - C phụ thuộc vào regex nhận diện cấu trúc văn bản luật, nên không áp dụng nguyên được cho tài liệu không có cấu trúc Chương/Điều.
    - Filter chỉ dùng được khi câu hỏi hoặc ngữ cảnh đã cung cấp giá trị lọc. Lọc sai sẽ loại mất đáp án.
    - Như q19 cho thấy, filter không giải quyết được lỗi xếp hạng trong cùng một chương.
  - **Điều kiện áp dụng:** văn bản pháp luật hoặc quy chế có cấu trúc rõ, và người dùng biết hoặc được hỏi lại phạm vi (luật nào, loại hình BHXH nào).
  - Kết luận chỉ đúng cho corpus 2 văn bản này và bộ 20 câu này, không suy rộng ra ngoài.
- **Hạn chế của dữ liệu, nhãn, test nhỏ, đo thời gian/chi phí:**
  - **Dữ liệu:** lỗi tách chữ ở BLLĐ; 1 trang lỗi font chưa OCR; hai văn bản khác trạng thái hiệu lực (bản hợp nhất và bản gốc); chunk bị giới hạn trong 1 trang nên Điều kéo sang trang sau bị tách (đã giảm bớt nhờ prefix "(tiếp)").
  - **Benchmark:**
    - Chỉ 2 văn bản nên không chia dev/test theo tài liệu được.
    - q15 (dev) và q19, q20 (test) cùng khai thác cấu trúc song song Chương V/VI, nên có nguy cơ rò rỉ.
    - Câu hỏi được viết sau khi đọc văn bản, nên dùng từ trùng với văn bản nhiều hơn câu hỏi của người dùng thật.
  - **Test nhỏ:** 5 câu, mỗi câu tương ứng 20 điểm phần trăm. Coherence chỉ có n=10. Mọi chênh lệch 1 câu không có ý nghĩa thống kê.
  - **Nhãn:**
    - Coherence, grounding và metadata được chấm sau khi đã thấy chỉ số tự động, nên có nguy cơ thiên lệch.
  - **Thời gian:** đo một lần trên CPU laptop (torch bản CPU, không dùng GPU) nên chỉ mang tính tham khảo. Chi phí bằng 0 vì model chạy local.
- **Nếu làm lại hoặc mở rộng, cải tiến gì?**
  - Ghép tiếp Điều qua ranh giới trang, vẫn lưu danh sách trang để truy vết, nhằm giảm việc tách Điều.
  - Thử hybrid retrieval (BM25 kết hợp dense) cho những câu có con số hoặc từ khóa đặc thù như q19.
  - Thử reranker, hoặc gộp các khoản ngắn cùng Điều thành chunk lớn hơn.
  - Sửa lỗi tách chữ bằng một nguồn PDF khác hoặc bằng OCR rồi đo lại.
  - Tăng số câu test và chia theo chủ đề.
  - Nhờ người thứ hai chấm độc lập để đo mức đồng thuận giữa người chấm.

## Sử dụng AI

Bài làm có dùng trợ lý AI (Claude, Anthropic) trong Claude Code, cho các việc sau:
- Tìm nguồn và tải PDF.
- Viết code pipeline, các script kiểm tra và tổng hợp.
- Soạn bộ câu hỏi benchmark.

Cách kiểm tra:
- Evidence được xác minh tự động trên text PDF (`verify_benchmark.py`).
- Metadata được đối chiếu bằng một script độc lập với code pipeline.
- Tính lặp lại của ingest đã được kiểm chứng bằng cách chạy lại.
- Tác giả đã đọc lại câu hỏi, các nhãn và báo cáo.

Toàn bộ số liệu trong báo cáo lấy từ các file kết quả đã chạy thật, có dẫn link ở trên.
