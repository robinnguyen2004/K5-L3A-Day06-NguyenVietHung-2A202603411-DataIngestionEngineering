import hashlib
import re

from .ingestion import structure_events
from .models import Chunk, DocumentPage

# A new paragraph starts at a structural marker at the beginning of a line:
# Chương / Mục / Điều N. / khoản "1." / điểm "a)".
PARA_START = re.compile(r"^(Chương [IVXLC]+|Mục \d+|Điều \d+[a-zđ]?\.|\d+[a-z]?\.\s|[a-zđ]\)\s)")
HEADING = re.compile(r"^(Chương [IVXLC]+|Mục \d+|Điều \d+[a-zđ]?\.)")
SECTION_HEADING = re.compile(r"^(Chương [IVXLC]+|Mục \d+)")
ARTICLE_LINE = re.compile(r"^(Điều \d+[a-zđ]?\.)\s*(.*)$")
WORD_SNAP = 20  # max chars to move a fixed-size boundary to the nearest space


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _span_structure(page: DocumentPage, events, start: int, end: int) -> tuple[list[str], list[str]]:
    """Chapters/articles covering text[start:end] (state at start + headings inside the span)."""
    chapter = page.metadata.get("chapter_at_start")
    article = page.metadata.get("article_at_start")
    for offset, kind, value in events:  # state in effect at `start`
        if offset > start:
            break
        if kind == "chapter":
            chapter, article = value, None
        else:
            article = value
    if page.text[start:start + 12].startswith(("Chương ", "Mục ")):
        article = None  # a new chapter/section opens here; the previous Điều is not in the chunk
    chapters = [chapter] if chapter else []
    articles = [article] if article else []
    for offset, kind, value in events:  # headings inside the span
        if start < offset < end:
            (chapters if kind == "chapter" else articles).append(value)
    return list(dict.fromkeys(chapters)), list(dict.fromkeys(articles))


def _make_chunk(page: DocumentPage, chunk_id: str, text: str, start: int, end: int,
                events, **extra) -> Chunk:
    chapters, articles = _span_structure(page, events, start, end)
    return Chunk(
        chunk_id=chunk_id,
        document_id=page.document_id,
        source=page.source,
        page=page.page,
        text=text,
        metadata={
            "law_name": page.metadata.get("law_name"),
            "chapters": chapters,
            "articles": [a.split(".")[0] for a in articles],  # "Điều 25"
            "char_start": start,
            "char_end": end,
            "chars": len(text),
            "content_hash": content_hash(text),
            **extra,
        },
    )


def fixed_size(page: DocumentPage, size: int, overlap: int) -> list[Chunk]:
    """Overlapping character windows within one page.

    Boundaries are moved back by at most WORD_SNAP characters to the nearest space so words
    are not cut in half; otherwise structure is ignored on purpose (baseline A).
    """
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError("Require size > 0 and 0 <= overlap < size")
    text, events = page.text, structure_events(page.text)
    chunks: list[Chunk] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            space = max(text.rfind(" ", end - WORD_SNAP, end), text.rfind("\n", end - WORD_SNAP, end))
            if space > start:
                end = space
        piece = text[start:end].strip()
        if piece:
            chunk_id = f"{page.document_id}:p{page.page:03d}:fixed{size}o{overlap}:{len(chunks):02d}"
            chunks.append(_make_chunk(page, chunk_id, piece, start, end, events))
        if end >= len(text):
            break
        next_start = end - overlap
        space = text.find(" ", next_start, next_start + WORD_SNAP)
        start = space + 1 if space != -1 and space + 1 < end else max(next_start, start + 1)
    return chunks


def _paragraph_spans(text: str) -> list[tuple[int, int]]:
    """Merge wrapped PDF lines into paragraphs; return (start, end) offsets."""
    spans: list[list[int]] = []
    offset, previous_blank = 0, True
    for line in text.split("\n"):
        start, end = offset, offset + len(line)
        offset = end + 1
        if not line.strip():
            previous_blank = True
            continue
        if not spans or previous_blank or PARA_START.match(line):
            spans.append([start, end])
        else:
            spans[-1][1] = end
        previous_blank = False
    return [(s, e) for s, e in spans]


def _split_long(text: str, start: int, end: int, max_size: int) -> list[tuple[int, int]]:
    """Split an oversized paragraph at sentence/clause punctuation, then at spaces."""
    pieces, cursor = [], start
    while end - cursor > max_size:
        window = text[cursor:cursor + max_size]
        cut = max(window.rfind("; "), window.rfind(". "), window.rfind(": "))
        if cut < max_size // 3:
            cut = window.rfind(" ")
        if cut <= 0:
            cut = max_size - 1
        pieces.append((cursor, cursor + cut + 1))
        cursor += cut + 1
        while cursor < end and text[cursor].isspace():
            cursor += 1
    if cursor < end:
        pieces.append((cursor, end))
    return pieces


def by_paragraph(page: DocumentPage, max_size: int) -> list[Chunk]:
    """Structure-aware chunks within one page.

    - Paragraphs = Chương/Mục/Điều headings, khoản "1.", điểm "a)" (wrapped lines merged).
    - A new chunk always starts at a new Điều (Chương/Mục headings stay with the next Điều).
    - Paragraphs of the same Điều are packed up to max_size; oversized ones are split.
    - A chunk that continues an Điều (from the previous chunk or previous page) is prefixed
      with that Điều's heading + "(tiếp)" so it can be understood on its own.
    - Heading-only fragments at the end of a page are dropped (see flush()).
    """
    if max_size <= 0:
        raise ValueError("max_size must be > 0")
    text, events = page.text, structure_events(page.text)
    units: list[tuple[int, int]] = []
    for s, e in _paragraph_spans(text):
        units.extend(_split_long(text, s, e, max_size) if e - s > max_size else [(s, e)])

    chunks: list[Chunk] = []
    current: list[tuple[int, int]] = []
    current_len, has_body = 0, False
    article = page.metadata.get("article_at_start")
    chunk_article = article  # article in effect when the current chunk started

    def flush() -> None:
        nonlocal current, current_len, has_body
        if not current:
            return
        if not has_body:
            # Only headings left at the end of the page: the body is on the next page, whose first
            # chunk repeats the Điều heading as "(tiếp)" prefix, so this fragment is dropped.
            current, current_len = [], 0
            return
        body = "\n".join(" ".join(text[s:e].split()) for s, e in current)
        prefix = ""
        if chunk_article and not HEADING.match(body):
            prefix = f"{chunk_article} (tiếp)\n"
        chunk_id = f"{page.document_id}:p{page.page:03d}:para{max_size}:{len(chunks):02d}"
        chunks.append(_make_chunk(page, chunk_id, prefix + body, current[0][0], current[-1][1],
                                  events, context_prefix=bool(prefix)))
        current, current_len, has_body = [], 0, False

    for s, e in units:
        piece = " ".join(text[s:e].split())
        starts_heading = bool(HEADING.match(piece))
        # A heading-only unit (Chương/Mục line, or a one-line "Điều N. Title") never ends a chunk
        # on its own, so a heading is not separated from the body that follows it.
        heading_only = bool(SECTION_HEADING.match(piece)) or (
            piece.startswith("Điều ") and "\n" not in text[s:e])
        if starts_heading and has_body:
            flush()
        elif has_body and current_len + len(piece) + 1 > max_size:
            flush()
        if not current:
            chunk_article = article  # used as prefix only if the chunk does not open with a heading
        if piece.startswith("Điều "):
            line_end = text.find("\n", s, e)
            m = ARTICLE_LINE.match(text[s:line_end if line_end != -1 else e])
            if m:
                article = f"{m.group(1)} {m.group(2)}".strip()
        current.append((s, e))
        current_len += len(piece) + 1
        if not heading_only:
            has_body = True
    flush()
    return chunks
