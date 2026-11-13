"""Kiểm chứng benchmark/questions.jsonl trước khi chạy thử nghiệm.

Kiểm tra:
1. Số câu, split (>=15 dev, >=5 test), số câu filter (>=3, >=1 test), đủ trường bắt buộc.
2. evidence_quote có thật sự nằm ở gold_page sau chuẩn hóa:
   - "exact": khớp sau chuẩn hóa NFC + gộp khoảng trắng;
   - "nospace": chỉ khớp khi bỏ toàn bộ khoảng trắng (do PDF tách sai chữ, ví dụ "lao đ ộng").
3. Giá trị filter có tồn tại trong metadata của gold page (data/manifest.json).
4. Liệt kê các trang KHÁC cũng chứa evidence → ứng viên gold thay thế, cần người xem xét.

Cách dùng (từ thư mục starter/):
    python scripts/verify_benchmark.py
"""
import json
import re
import sys
import unicodedata
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[2]
REQUIRED = ["id", "split", "question", "expected_answer", "gold_source_id", "gold_page", "evidence_quote"]


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip().lower()


def nospace(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", text)).lower()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    manifest = json.loads((ROOT / "data/manifest.json").read_text(encoding="utf-8"))
    questions = [json.loads(line) for line in
                 (ROOT / "benchmark/questions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]

    # Text + metadata của mọi trang được tính.
    pages: dict[tuple[str, int], dict] = {}
    for src in manifest["sources"]:
        reader = PdfReader(ROOT / src["file"])
        for p in src["pages"]:
            text = reader.pages[p["page"] - 1].extract_text() or ""
            pages[(src["source_id"], p["page"])] = {
                "norm": norm(text), "nospace": nospace(text),
                "meta": {"law_name": src["law_name"], "chapter": p["chapters"]},
            }

    errors, report = [], []
    for q in questions:
        missing = [f for f in REQUIRED if f not in q or q[f] in (None, "", [])]
        if missing:
            errors.append(f"{q.get('id')}: thiếu trường {missing}")
            continue
        ev_n, ev_s = norm(q["evidence_quote"]), nospace(q["evidence_quote"])
        gold = [(q["gold_source_id"], pg) for pg in q["gold_page"]]
        result = {"id": q["id"], "split": q["split"], "gold": [f"{s}:p{p}" for s, p in gold]}

        match = None
        for key in gold:
            page = pages.get(key)
            if page is None:
                errors.append(f"{q['id']}: {key} không nằm trong các trang được tính của manifest")
            elif ev_n in page["norm"]:
                match = "exact"
            elif ev_s in page["nospace"] and match is None:
                match = "nospace"
        result["evidence_match"] = match or "NOT_FOUND"
        if not match:
            errors.append(f"{q['id']}: evidence không có ở gold page")

        if q.get("filter"):
            ok = True
            for key in gold:
                meta = pages.get(key, {}).get("meta", {})
                for field, value in q["filter"].items():
                    actual = meta.get(field)
                    if not (value == actual or (isinstance(actual, list) and value in actual)):
                        ok = False
                        errors.append(f"{q['id']}: gold page {key} không có {field}={value} (thực tế: {actual})")
            result["filter"] = q["filter"]
            result["filter_matches_gold"] = ok

        others = [f"{s}:p{p}" for (s, p), page in pages.items()
                  if (s, p) not in gold and ev_s in page["nospace"]]
        result["evidence_also_on"] = others
        report.append(result)

    dev = sum(q["split"] == "dev" for q in questions)
    test = sum(q["split"] == "test" for q in questions)
    flt = [q for q in questions if q.get("filter")]
    flt_test = sum(q["split"] == "test" for q in flt)
    summary = {"total": len(questions), "dev": dev, "test": test,
               "filter_questions": len(flt), "filter_in_test": flt_test,
               "evidence_exact": sum(r.get("evidence_match") == "exact" for r in report),
               "evidence_nospace_only": sum(r.get("evidence_match") == "nospace" for r in report)}
    if len(questions) < 20: errors.append("Ít hơn 20 câu")
    if dev < 15 or test < 5: errors.append("Cần >=15 dev và >=5 test")
    if len(flt) < 3 or flt_test < 1: errors.append("Cần >=3 câu filter, >=1 câu filter ở test")
    if len({q["id"] for q in questions}) != len(questions): errors.append("Trùng id câu hỏi")

    out = ROOT / "results/benchmark_verification.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "errors": errors, "questions": report},
                              ensure_ascii=False, indent=2), encoding="utf-8")

    for r in report:
        extra = f" | cũng có ở: {', '.join(r['evidence_also_on'])}" if r["evidence_also_on"] else ""
        flt_s = f" | filter={r['filter']} ok={r['filter_matches_gold']}" if "filter" in r else ""
        print(f"{r['id']} [{r['split']}] {','.join(r['gold'])}: {r['evidence_match']}{flt_s}{extra}")
    print("\nTóm tắt:", summary)
    print("Lỗi:" if errors else "Không có lỗi.", *errors, sep="\n  ")
    print(f"→ {out.relative_to(ROOT)}")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
