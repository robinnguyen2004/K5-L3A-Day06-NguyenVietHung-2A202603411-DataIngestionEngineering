# Nhãn chấm thủ công: phương pháp

| File | Nội dung | Số dòng |
|---|---|---|
| `coherence_labels.csv` | Coherence 0–2 của chunk chứa 10 vị trí nguồn cố định × A/B/C | 30 |
| `grounding_labels.csv` | Grounding 0–2 của top-3 trên 5 câu test × A/B/C | 15 |
| `metadata_audit.csv` | Kiểm tra source/page/law_name/chapters/articles của top-3, 5 câu test × A/B/C | 45 |

Tổng hợp bằng `python scripts/summarize_labels.py` (chạy từ `starter/`), kết quả ở `results/manual_summary.json`.

## Chọn mẫu
- **Coherence:** 10 trang cách đều nhau trong 153 trang được tính (sắp theo `source_id`, `page`). Vị trí là ký tự ở giữa trang. Mẫu được chọn tự động trước khi chấm (`python -m src.run samples`). C dùng chung chunk với B nên cùng điểm.
- **Grounding và metadata:** toàn bộ 5 câu test × top-3, sau khi chiến lược đã được chọn trên dev (`eval --split test --frozen`).

## Quy ước chấm
- **Coherence** (chấm cả chunk, vì đó là ngữ cảnh mà LLM nhận được):
  - 0: câu ở vị trí chấm mất chủ thể hoặc bị cắt nên không hiểu được.
  - 1: ý chính đọc được nhưng có mảnh câu cụt ở đầu/cuối, thiếu phần liệt kê/ngoại lệ, hoặc không biết đang thuộc Điều nào.
  - 2: tự hiểu được, trọn khoản/điều.
  - Lỗi tách chữ của PDF ("lao đ ộng") và tên điều bị cụt trong prefix được ghi vào lý do nhưng không trừ điểm.
- **Grounding** (chấm top-3 gộp lại, so với `expected_answer`):
  - 0: không có bằng chứng.
  - 1: có bằng chứng nhưng thiếu điều kiện/ngoại lệ cần thiết.
  - 2: đủ để trả lời và truy được nguồn.
  - Chỉ đánh giá evidence được truy xuất, **không** phải độ chính xác câu trả lời của LLM.
- **Metadata:** Y khi text của chunk thực sự nằm ở `page` của `source`, `law_name` đúng văn bản, và `chapters`/`articles` khớp tiêu đề Chương/Điều bao phủ đoạn đó.
  - Việc đối chiếu dùng một script độc lập: tự trích text thô bằng pypdf, xác định lại Chương/Điều bằng regex riêng, không dùng code chuẩn hóa hay chunking của pipeline.
  - Script đã được thử với dữ liệu sai cố ý (trang sai, Chương V so với VI) và đều phát hiện được.
- **Filter tuân thủ:** lấy từ cột tự động `auto_matches_filter`. Một câu tuân thủ khi cả 3 kết quả đều khớp filter của câu hỏi.
