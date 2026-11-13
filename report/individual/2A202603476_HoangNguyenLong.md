# Báo cáo cá nhân — Day 6

## Dữ liệu và pipeline
- **Chủ đề, nguồn/quyền, số trang và quy tắc tính trang:**
  - Corpus: **Nghị định số 168/2024/NĐ-CP** ngày 26/12/2024 của Chính phủ quy định xử phạt vi phạm hành chính về trật tự, an toàn giao thông trong lĩnh vực giao thông đường bộ; trừ điểm, phục hồi điểm giấy phép lái xe.
  - Nguồn & quyền: Văn bản quy phạm pháp luật công khai của Chính phủ Việt Nam, chuyển đổi từ `168_2024_ND-CP_619502 (2).doc` sang `starter/data/nd_168_2024.pdf` (manifest tại [data/manifest.json](../../data/manifest.json)).
  - Số trang: **105/105 trang** vật lý đều có nội dung hợp lệ (254.901 ký tự sau chuẩn hóa), không có trang bìa, mục lục hay trang trống.
- **Chuẩn hóa, lỗi và giới hạn:**
  - Chuẩn hóa Unicode NFKC, chuẩn hóa xuống dòng (`\r\n` → `\n`), gom khoảng trắng/tab thừa nhưng giữ cấu trúc đoạn và ký hiệu `Chương`, `Mục`, `Điều`, khoản, điểm.
  - Log đọc PDF: `0` trang rỗng, `0` trang lỗi. Giới hạn: `pypdf` ngắt dòng theo chiều rộng trang nên một số câu dài bị tách thành nhiều dòng; hàm `_split_legal_paragraphs` đã gom lại theo cấu trúc điều khoản.
- **Embedding model, vector store, metric, lệnh chạy và chi phí:**
  - Embedding model: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (local CPU, **384 chiều**, `normalize_embeddings=True`, `sentence-transformers==6.3.0`).
  - Vector store: **PostgreSQL 16.16 + pgvector 0.8.7** (Docker `pgvector/pgvector:0.8.7-pg16`, bảng `document_chunks`, tìm kiếm chính xác theo cosine distance `<=>`).
  - Lệnh chạy từ `starter/`:
    ```powershell
    docker compose -p day6_student_starter up -d --wait
    .\.venv\Scripts\python.exe scripts\check_setup.py
    .\.venv\Scripts\python.exe -m src.run
    ```
  - Chi phí: **0 USD** (chạy hoàn toàn local). Kiểm tra nạp lại trên chiến lược A cho thấy số dòng trước và sau re-upsert đều là **607** (không nhân đôi).
- **Metadata bắt buộc, trường lọc bổ sung, nguồn giá trị và lý do chọn:**
  - Bắt buộc: `document_id` (`nd-168-2024`), `source` (`starter/data/nd_168_2024.pdf`), `page` (`1..105`).
  - Bổ sung: `chapter` (`Chương I`..`Chương IV`), `section` (`Mục 1`..`Mục 5`), `year` (`2024`), `document_type` (`nghi_dinh`), `language` (`vi`).
  - Lý do chọn `chapter`: Nghị định có nhiều từ khóa trùng lặp giữa phần quy định hành vi/mức phạt (`Chương II`) và phần thẩm quyền/thủ tục trừ điểm GPLX (`Chương III`), nên lọc theo `chapter` giúp thu hẹp phạm vi tìm kiếm khi ngữ cảnh câu hỏi chỉ rõ Chương.

## Cấu hình và benchmark
- **A / B / C (tham số cụ thể, khác biệt duy nhất B–C):**
  - **A (Baseline fixed-size):** `size=500`, `overlap=50`, không filter.
  - **B (Structure-aware):** `by_paragraph` với `max_size=700`, `overlap=80`, không filter.
  - **C (Structure-aware + Metadata filter):** Chunking giống hệt **B** (`by_paragraph`, `max_size=700`, `overlap=80`), khác biệt duy nhất là áp dụng filter `{"chapter": ...}` ở bước truy xuất cho các câu hỏi có trường `filter`.
- **Bộ 20 câu hỏi & kiểm chứng ([benchmark/questions.json](../../benchmark/questions.json)):**
  - Chia trước khi chạy: **15 dev** (`q01`–`q15`) / **5 test** (`q16`–`q20`), gồm câu trực tiếp, diễn đạt lại, điều kiện/ngoại lệ và **4 câu kiểm tra metadata filter** (`q12, q13, q14` trong dev; `q19` trong test).
  - Tất cả **20/20 `evidence_quote`** đã được kiểm chứng khớp chính xác trên `gold_page` sau chuẩn hóa trước khi chạy thử nghiệm.
- **Tiêu chí chọn chiến lược (chốt trước khi xem test):**
  - Ưu tiên `Evidence Hit@3` trên tập `dev`, tiếp theo là `Chunk Coherence` & `Grounding Quality`, cuối cùng là thời gian/số lượng chunk.

## Kết quả

| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian (ingest / query) | Chi phí |
|---|---|---:|---:|---:|---:|---:|
| A | dev | 4/15 (26.67%) | 7/15 (46.67%) | 607 | 24.34s / 1.16s | \$0 |
| A | test | 2/5 (40.00%) | 2/5 (40.00%) | 607 | 24.34s / 1.16s | \$0 |
| B | dev | 5/15 (33.33%) | 7/15 (46.67%) | 495 | 19.60s / 0.97s | \$0 |
| B | test | 1/5 (20.00%) | 1/5 (20.00%) | 495 | 19.60s / 0.97s | \$0 |
| C | dev | 5/15 (33.33%) | 8/15 (53.33%) | 495 | 19.60s / 1.03s | \$0 |
| C | test | 1/5 (20.00%) | 1/5 (20.00%) | 495 | 19.60s / 1.03s | \$0 |

| Strategy | Coherence TB /2 (n=10) | Metadata đủ & đúng (n/N) | Filter tuân thủ (n/N hoặc N/A) | Grounding 0/1/2 (số câu) & TB /2 |
|---|---:|---:|---:|---|
| A | 0.60 (10) | 15/15 | N/A | 0: 3, 1: 0, 2: 2 — TB **0.80/2** |
| B | 1.60 (10) | 15/15 | N/A | 0: 2, 1: 2, 2: 1 — TB **0.80/2** |
| C | 1.60 (10) | 15/15 | 4/4 (dev 3/3, test 1/1) | 0: 2, 1: 2, 2: 1 — TB **0.80/2** |

- **Đường dẫn trace & nhãn thủ công:**
  - Trace top-3 đầy đủ: [starter/results/traces.json](../../starter/results/traces.json)
  - Thống kê tổng hợp & ingestion: [starter/results/summary.json](../../starter/results/summary.json), [starter/results/ingestion_stats.json](../../starter/results/ingestion_stats.json)
  - Mẫu 10 vị trí coherence (trang 1, 2, 3, 6, 7, 8, 9, 10, 15, 18): [starter/results/coherence_samples.json](../../starter/results/coherence_samples.json)
  - Nhãn chấm thủ công (tác giả tự chấm): [starter/results/manual_audit.json](../../starter/results/manual_audit.json)

## Phân tích và kết luận
- **So sánh A–B và B–C:**
  - **A vs B (tác động của chunking):** B giảm 18.5% số chunk (495 so với 607), rút ngắn thời gian ingest từ 24.34s xuống 19.60s, tăng `Hit@1` trên dev từ 4/15 lên 5/15 và tăng mạnh `Coherence` từ **0.60/2** lên **1.60/2** nhờ không cắt ngang từ/câu như A. Tuy nhiên trên tập test nhỏ (5 câu), A trúng `q16` (trang 28) còn B không trúng do đoạn ở trang 29 có cosine similarity cao hơn nhẹ (0.825).
  - **B vs C (tác động của metadata filter):** Trên `q13` (dev, lọc `Chương III`), B bị nhiễu bởi các đoạn ở Chương II nên trượt, còn C lọc đúng vào `Chương III` và đạt Hit@3, nâng dev `Evidence Hit@3` từ **7/15 (46.67%)** lên **8/15 (53.33%)** với tỷ lệ tuân thủ filter **4/4 (100%)**.
- **2 ví dụ lỗi cụ thể:**
  1. `q19` (test, `gold_page=99`, `nd-168-2024`): Cả A, B, C đều không trả về trang 99 trong top-3. Ở chiến lược C (lọc `Chương III`), cả 3 kết quả đều nằm ở trang 98 (`Điều 50` về nguyên tắc trừ điểm GPLX) vì câu hỏi chứa cụm "trừ điểm giấy phép lái xe" trùng mạnh hơn so với đoạn quy định "thông báo bằng văn bản / phương thức điện tử" ở trang 99.
  2. `q18` (test, `gold_page=73`, `nd-168-2024`): Hỏi mức phạt vượt quá tải trọng trên 50%. B và C truy xuất được đầu `Điều 34` ở trang 72 (nêu tiêu đề quá khổ, quá tải) nhưng chưa xuống tới khoản 5 ở trang 73 vì embedding đa ngữ `MiniLM-L12-v2` nhạy với cụm "xe quá tải, quá khổ" hơn là con số "50%".
- **Chiến lược chọn, đánh đổi, điều kiện áp dụng:**
  - Chọn **Chiến lược C** theo tiêu chí đã chốt trên dev (`Evidence Hit@3 = 8/15` cao nhất, `Coherence = 1.60/2`, ít chunk hơn và nhanh hơn A). Đánh đổi: cần biết trước `chapter` từ ngữ cảnh người dùng; nếu metadata gán ở cấp trang bị lệch tại trang chuyển tiếp (ví dụ trang 100 chuyển từ Chương III sang Chương IV), filter có thể bỏ sót đoạn chuyển tiếp.
- **Hạn chế:**
  - Tập test chỉ có 5 câu nên độ dao động lớn (1 câu = 20%); người chấm thủ công là tác giả nên có nguy cơ thiên lệch.
  - Model `paraphrase-multilingual-MiniLM-L12-v2` thiên về khớp ngữ nghĩa tổng quát, chưa mạnh về khớp chính xác số điều/khoản hoặc tỷ lệ phần trăm ("50%", "05 km/h") trong văn bản luật tiếng Việt.
- **Cải tiến nếu làm lại/mở rộng:**
  - Chunk theo ranh giới `Điều` và lưu tiêu đề `Điều` vào đầu mỗi chunk con để tránh mất chủ thể khi sang trang mới.
  - Kết hợp **Hybrid Retrieval (Dense + BM25)** để bắt chính xác số Điều/Khoản/mức % và dùng embedding model tiếng Việt chuyên sâu hơn (như `bge-m3` hoặc `vietnamese-bi-encoder`).

