"""Sinh data/manifest.json từ data/sources.json và các file PDF.

- Đếm ký tự (sau chuẩn hóa NFC + gộp khoảng trắng) của từng trang được tính.
- Gắn metadata `chapter` cho từng trang, lấy từ tiêu đề "Chương ..." thật sự có trong PDF.
- Cảnh báo trang ít chữ / lỗi font, và dừng nếu tổng số trang được tính < 30.

Cách dùng (từ thư mục starter/):
    python scripts/build_manifest.py
"""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parent))
from inspect_pdf import page_stats  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
MIN_PAGES = 30


def parse_ranges(spec: str) -> list[int]:
    pages: list[int] = []
    for part in spec.split(","):
        start, _, end = part.strip().partition("-")
        pages.extend(range(int(start), int(end or start) + 1))
    return pages


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_source(src: dict) -> dict:
    path = ROOT / src["file"]
    reader = PdfReader(path)
    counted = set(parse_ranges(src["counted_pages"]))

    pages, warnings = [], []
    current_chapter = None
    for number, page in enumerate(reader.pages, start=1):
        stats = page_stats(page.extract_text() or "")
        # Chương đang hiệu lực ở đầu trang + các chương bắt đầu trên trang này.
        chapters = ([current_chapter] if current_chapter else []) + stats["chapters"]
        chapters = list(dict.fromkeys(chapters))
        if stats["chapters"]:
            current_chapter = stats["chapters"][-1]
        if number not in counted:
            continue
        if stats["chars"] < 200 or stats["vi_ratio"] < 0.12:
            warnings.append(f"p{number}: {stats['chars']} ký tự, vi_ratio={stats['vi_ratio']:.2f}")
        pages.append({
            "page_id": f"{src['source_id']}:p{number}",
            "page": number,
            "chars": stats["chars"],
            "chapters": chapters,
            "split_word_hits": stats["split_words"],
        })

    return {
        **src,
        "sha256": sha256(path),
        "physical_pages": len(reader.pages),
        "counted_page_total": len(pages),
        "char_total": sum(p["chars"] for p in pages),
        "chapter_values": list(dict.fromkeys(c for p in pages for c in p["chapters"])),
        "warnings": warnings,
        "pages": pages,
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sources = json.loads((ROOT / "data/sources.json").read_text(encoding="utf-8"))
    built = [build_source(s) for s in sources]
    total = sum(s["counted_page_total"] for s in built)

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator": "starter/scripts/build_manifest.py",
        "page_counting_rule": (
            "Đơn vị = 1 trang PDF vật lý. Chỉ tính trang có nội dung điều luật (Chương/Điều/Khoản), "
            "kể cả trang có quốc hiệu hoặc chữ ký nếu phần còn lại là nội dung điều luật. Loại trang chỉ có "
            "nơi nhận/chữ ký/xác thực hoặc trang không trích được text đọc được. Số ký tự = độ dài text "
            "sau chuẩn hóa Unicode NFC và gộp khoảng trắng (pypdf extract_text)."
        ),
        "filter_fields": {
            "law_name": "Giá trị cấp tài liệu (bo-luat-lao-dong | luat-bao-hiem-xa-hoi), lấy từ tiêu đề văn bản.",
            "chapter": "Số chương La Mã, lấy từ dòng tiêu đề 'Chương ...' trong PDF; trang nằm giữa hai chương có thể thuộc 2 chương.",
        },
        "total_counted_pages": total,
        "total_chars": sum(s["char_total"] for s in built),
        "sources": built,
    }
    out = ROOT / "data/manifest.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    for s in built:
        print(f"{s['source_id']}: {s['counted_page_total']}/{s['physical_pages']} trang được tính, "
              f"{s['char_total']:,} ký tự, chương {s['chapter_values'][0]}–{s['chapter_values'][-1]}")
        for w in s["warnings"]:
            print(f"  ⚠️ {w}")
    print(f"Tổng: {total} trang nội dung → {out.relative_to(ROOT)}")
    if total < MIN_PAGES:
        sys.exit(f"Chưa đủ {MIN_PAGES} trang nội dung!")


if __name__ == "__main__":
    main()
