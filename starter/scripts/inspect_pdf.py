"""In thống kê từng trang PDF để quyết định trang nào được tính vào corpus.

Cách dùng (từ thư mục starter/):
    python scripts/inspect_pdf.py data/luat-bhxh-41-2024.pdf
    -> ghi ra ../results/inspect_luat-bhxh-41-2024.txt (UTF-8) và in ra màn hình.

Script tự ghi file UTF-8; KHÔNG dùng `> file.txt` trong Windows PowerShell 5.1
vì toán tử `>` ở đó ghi UTF-16 và làm hỏng tiếng Việt.
"""
import re
import sys
import unicodedata
from pathlib import Path

from pypdf import PdfReader

VI_CHARS = set("ăâđêôơưàáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ")
# Một số mẫu từ bị tách sai do font/PDF (ví dụ "lao đ ộng", "c ủa").
SPLIT_WORD = re.compile(r"\b(đ ộng|vi ệc|c ủa|ngư ời|đ ịnh|h ợp|đ ồng|lu ật|kho ản|đi ều)\b")
CHAPTER = re.compile(r"(?m)^\s*Chương\s+([IVXLC]+)\S*\s*$")


def page_stats(text: str) -> dict:
    flat = " ".join(unicodedata.normalize("NFC", text).split())
    letters = [c for c in flat.lower() if c.isalpha()]
    return {
        "chars": len(flat),
        "vi_ratio": sum(c in VI_CHARS for c in letters) / max(1, len(letters)),
        "split_words": len(SPLIT_WORD.findall(flat)),
        "chapters": CHAPTER.findall(text),
        "preview": flat[:90],
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    path = Path(sys.argv[1])
    reader = PdfReader(path)
    lines = [f"{path.name}: {len(reader.pages)} trang vật lý",
             "page | chars | vi_ratio | split_words | chapter_heading | preview"]
    for number, page in enumerate(reader.pages, start=1):
        s = page_stats(page.extract_text() or "")
        flag = " [CANH BAO]" if s["chars"] < 200 or s["vi_ratio"] < 0.12 else ""
        chapters = ",".join(s["chapters"]) or "-"
        lines.append(f"p{number:>3} | {s['chars']:>5} | {s['vi_ratio']:.2f} | {s['split_words']:>3} | "
                     f"{chapters:<7} | {s['preview']}{flag}")

    out = Path(__file__).resolve().parents[2] / "results" / f"inspect_{path.stem}.txt"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\n-> Đã ghi {out} (UTF-8)")


if __name__ == "__main__":
    main()
