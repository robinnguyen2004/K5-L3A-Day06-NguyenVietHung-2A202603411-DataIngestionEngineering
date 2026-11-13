"""Aggregate manual labels (results/manual/*.csv) into results/manual_summary.json.

Cách dùng (từ thư mục starter/):
    python scripts/summarize_labels.py
"""
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANUAL = ROOT / "results" / "manual"


def read(name: str) -> list[dict]:
    with (MANUAL / name).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    out: dict = {"coherence": {}, "grounding": {}, "metadata": {}}

    by = defaultdict(list)
    for r in read("coherence_labels.csv"):
        if r["coherence_score_0_1_2"] == "":
            sys.exit(f"Thiếu điểm coherence: {r['position_id']} {r['strategy']}")
        by[r["strategy"]].append(int(r["coherence_score_0_1_2"]))
    for s, v in sorted(by.items()):
        out["coherence"][s] = {"n": len(v), "mean_of_2": round(sum(v) / len(v), 2),
                               "count_0_1_2": [v.count(0), v.count(1), v.count(2)]}

    by = defaultdict(list)
    for r in read("grounding_labels.csv"):
        if r["grounding_score_0_1_2"] == "":
            sys.exit(f"Thiếu điểm grounding: {r['question_id']} {r['strategy']}")
        by[r["strategy"]].append(int(r["grounding_score_0_1_2"]))
    for s, v in sorted(by.items()):
        out["grounding"][s] = {"n": len(v), "mean_of_2": round(sum(v) / len(v), 2),
                               "count_0_1_2": [v.count(0), v.count(1), v.count(2)]}

    rows = read("metadata_audit.csv")
    by_rows = defaultdict(list)
    for r in rows:
        if r["metadata_correct_Y_N"] not in ("Y", "N"):
            sys.exit(f"Thiếu nhãn metadata: {r['question_id']} {r['strategy']} rank {r['rank']}")
        by_rows[r["strategy"]].append(r)
    for s, items in sorted(by_rows.items()):
        correct = sum(r["metadata_correct_Y_N"] == "Y" for r in items)
        # Filter compliance per question = all of its top-3 match the question's filter.
        per_q = defaultdict(list)
        for r in items:
            if r["question_filter"] not in ("", "null"):
                per_q[r["question_id"]].append(r["auto_matches_filter"] == "True")
        compliant = sum(all(v) for v in per_q.values())
        out["metadata"][s] = {
            "correct_records": f"{correct}/{len(items)}",
            "filter_compliance_top3": f"{compliant}/{len(per_q)}" if per_q else "N/A",
            "errors": [f"{r['question_id']} rank {r['rank']}: {r['error_note']}"
                       for r in items if r["metadata_correct_Y_N"] == "N"],
        }

    (ROOT / "results" / "manual_summary.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{'Strategy':<9}{'Coherence /2':>14}{'Metadata đúng':>15}{'Filter@3':>10}{'Grounding 0/1/2':>17}{'TB /2':>7}")
    for s in sorted(out["coherence"]):
        c, g, m = out["coherence"][s], out["grounding"][s], out["metadata"][s]
        print(f"{s:<9}{c['mean_of_2']:>8} (n={c['n']}){m['correct_records']:>15}{m['filter_compliance_top3']:>10}"
              f"{'/'.join(map(str, g['count_0_1_2'])):>17}{g['mean_of_2']:>7}")
    print("-> results/manual_summary.json")


if __name__ == "__main__":
    main()
