"""Read and normalize source PDFs while keeping traceability to source and page."""
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from .models import DocumentPage

MIN_CONTENT_CHARS = 200
VI_CHARS = set("ăâđêôơưàáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ")

_PAGE_NUMBER_LINE = re.compile(r"^\d{1,3}$")
# Structure headings in Vietnamese legal text. A heading must sit at the start of a line;
# "Điều N." requires the period so that wrapped references such as "Điều 2 của Luật này" are ignored.
CHAPTER_RE = re.compile(r"(?m)^Chương ([IVXLC]+)\S*[ \t]*$")
ARTICLE_RE = re.compile(r"(?m)^Điều (\d+[a-zđ]?)\.[ \t]*(.*)$")


def normalize_text(text: str) -> str:
    """Normalize Unicode (NFC) and whitespace, keep line breaks, drop printed page numbers.

    Known limitation: the text layer of some PDFs splits words ("lao đ ộng"). This is not
    repaired here (it cannot be done reliably); evaluation compares evidence without spaces.
    """
    text = unicodedata.normalize("NFC", text)
    text = text.replace(" ", " ").replace("­", "").replace("﻿", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = []
    for line in text.split("\n"):
        line = re.sub(r"[ \t\f\v]+", " ", line).strip()
        if _PAGE_NUMBER_LINE.match(line):
            continue  # printed page number on its own line
        lines.append(line)
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def vietnamese_ratio(text: str) -> float:
    letters = [c for c in text.lower() if c.isalpha()]
    return sum(c in VI_CHARS for c in letters) / max(1, len(letters))


def load_pdf(path: Path, document_id: str, source: str) -> list[DocumentPage]:
    """Extract every physical page; keep page number and source; flag empty/unreadable pages."""
    if not path.exists():
        raise FileNotFoundError(f"Source file not found: {path}")
    reader = PdfReader(path)
    pages = []
    for number, pdf_page in enumerate(reader.pages, start=1):
        try:
            raw = pdf_page.extract_text() or ""
            error = None
        except Exception as exc:  # keep going, but record the failure
            raw, error = "", f"{type(exc).__name__}: {exc}"
        text = normalize_text(raw)
        ratio = vietnamese_ratio(text)
        pages.append(DocumentPage(
            document_id=document_id,
            source=source,
            page=number,
            text=text,
            metadata={
                "chars": len(text),
                "vi_ratio": round(ratio, 3),
                "empty": len(text) < MIN_CONTENT_CHARS,
                "unreadable": ratio < 0.12,
                "extract_error": error,
            },
        ))
    return pages


def structure_events(text: str) -> list[tuple[int, str, str]]:
    """Return (offset, kind, value) for chapter/article headings, sorted by offset.

    For articles the value is the heading line, e.g. "Điều 25. Thời gian thử việc".
    """
    events = [(m.start(), "chapter", m.group(1)) for m in CHAPTER_RE.finditer(text)]
    events += [(m.start(), "article", f"Điều {m.group(1)}. {m.group(2)}".strip())
               for m in ARTICLE_RE.finditer(text)]
    return sorted(events)


def annotate_structure(pages: list[DocumentPage]) -> None:
    """Record the chapter and article in effect at the start of each page (per document)."""
    state: dict[str, dict[str, str | None]] = {}
    for page in pages:
        current = state.setdefault(page.document_id, {"chapter": None, "article": None})
        page.metadata["chapter_at_start"] = current["chapter"]
        page.metadata["article_at_start"] = current["article"]
        for _, kind, value in structure_events(page.text):
            current[kind] = value


def load_corpus(manifest_path: Path, root: Path) -> tuple[list[DocumentPage], dict[str, Any]]:
    """Load the counted pages listed in the manifest and return (pages, ingest_log)."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pages: list[DocumentPage] = []
    log: dict[str, Any] = {"sources": []}
    for src in manifest["sources"]:
        all_pages = load_pdf(root / src["file"], src["source_id"], src["file"])
        counted = {p["page"]: p for p in src["pages"]}
        kept, flagged = [], []
        for page in all_pages:
            info = counted.get(page.page)
            if info is None:
                continue
            page.metadata.update({
                "law_name": src["law_name"],
                "title": src["title"],
                "page_chapters": info["chapters"],
            })
            if page.metadata["empty"] or page.metadata["unreadable"] or page.metadata["extract_error"]:
                flagged.append({"page": page.page, **{k: page.metadata[k] for k in
                                ("chars", "vi_ratio", "extract_error")}})
            kept.append(page)
        missing = sorted(set(counted) - {p.page for p in kept})
        if missing:
            raise ValueError(f"{src['source_id']}: manifest pages missing from PDF: {missing}")
        pages.extend(kept)
        log["sources"].append({
            "source_id": src["source_id"],
            "physical_pages": len(all_pages),
            "counted_pages": len(kept),
            "excluded_pages": src.get("excluded_pages", {}),
            "flagged_counted_pages": flagged,
            "known_issues": src.get("known_issues", []),
        })
    annotate_structure(pages)
    log["total_counted_pages"] = len(pages)
    return pages, log
