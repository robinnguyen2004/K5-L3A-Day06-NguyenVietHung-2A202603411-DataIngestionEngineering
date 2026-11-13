"""Day 06 pipeline entry point.

Run from starter/:
    python -m src.run                  # ingest + evaluate dev (default)
    python -m src.run ingest           # load corpus, chunk A/B, embed, sync to pgvector
    python -m src.run eval --split dev # retrieve top-3 for A/B/C on dev questions
    python -m src.run eval --split test --frozen   # only after choosing the strategy on dev
    python -m src.run samples          # coherence positions (10 per strategy) for manual labels

Outputs go to ../results/ (repo root).
"""
import argparse
import csv
import json
import os
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .chunking import by_paragraph, fixed_size
from .evaluation import evaluate_query, summarize
from .ingestion import load_corpus
from .models import Chunk, DocumentPage

STARTER = Path(__file__).resolve().parents[1]
ROOT = STARTER.parent
RESULTS = ROOT / "results"
MANIFEST = ROOT / "data" / "manifest.json"
BENCHMARK = ROOT / "benchmark" / "questions.jsonl"
MIN_PAGES, MIN_QUESTIONS, MIN_DEV, MIN_TEST, MIN_FILTER = 30, 20, 15, 5, 3
TOP_K = 3

# Same corpus, embedding model, store, metric and questions for all strategies.
# A -> B changes only chunking; B -> C changes only metadata filtering (C reuses B's index).
STRATEGIES: dict[str, dict[str, Any]] = {
    "A": {"description": "Fixed-size 500 chars, overlap 50, no filter",
          "chunker": "fixed_size", "params": {"size": 500, "overlap": 50},
          "index": "A", "use_filter": False},
    "B": {"description": "Structure-aware (Điều/khoản/điểm), max 800 chars, no filter",
          "chunker": "by_paragraph", "params": {"max_size": 800},
          "index": "B", "use_filter": False},
    "C": {"description": "Same chunks/index as B + SQL metadata filter when the question provides one",
          "chunker": "by_paragraph", "params": {"max_size": 800},
          "index": "B", "use_filter": True},
}
CHUNKERS = {"fixed_size": fixed_size, "by_paragraph": by_paragraph}


# ---------------------------------------------------------------------------- helpers
def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:  # utf-8-sig: Excel shows Vietnamese
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def load_questions() -> list[dict[str, Any]]:
    questions = [json.loads(line) for line in BENCHMARK.read_text(encoding="utf-8").splitlines() if line.strip()]
    dev = sum(q["split"] == "dev" for q in questions)
    test = sum(q["split"] == "test" for q in questions)
    flt = [q for q in questions if q.get("filter")]
    if (len(questions) < MIN_QUESTIONS or dev < MIN_DEV or test < MIN_TEST or len(flt) < MIN_FILTER
            or not any(q["split"] == "test" for q in flt)):
        raise ValueError(f"Benchmark does not meet requirements: {len(questions)} questions, "
                         f"{dev} dev, {test} test, {len(flt)} with filter")
    return questions


def build_chunks(pages: list[DocumentPage], strategy: str) -> list[Chunk]:
    cfg = STRATEGIES[strategy]
    chunker = CHUNKERS[cfg["chunker"]]
    return [chunk for page in pages for chunk in chunker(page, **cfg["params"])]


def length_stats(values: list[int]) -> dict[str, Any]:
    return {"min": min(values), "mean": round(statistics.mean(values), 1),
            "median": statistics.median(values), "max": max(values), "total": sum(values)}


def make_components():
    load_dotenv(STARTER / ".env")
    from .embeddings import MyEmbedder  # imported here so `--help` stays fast
    from .store import PgVectorStore

    embedder = MyEmbedder()
    store = PgVectorStore(os.environ.get("DATABASE_URL", ""), embedder.dimensions, embedder.model_name)
    store.create_schema()
    return embedder, store


def model_snapshot(model_name: str) -> str | None:
    """Commit hash of the locally cached Hugging Face model, for reproducibility."""
    cache = Path(os.getenv("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
    ref = cache / f"models--{model_name.replace('/', '--')}" / "refs" / "main"
    return ref.read_text().strip() if ref.exists() else None


def run_info(embedder, store) -> dict[str, Any]:
    packages = {}
    for pkg in ["sentence-transformers", "torch", "transformers", "psycopg", "pgvector", "pypdf", "numpy"]:
        try:
            packages[pkg] = version(pkg)
        except Exception:
            packages[pkg] = None
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "embedding": {**embedder.describe(), "hf_snapshot": model_snapshot(embedder.model_name)},
        "vector_store": store.server_info(),
        "packages": packages,
        "strategies": STRATEGIES,
        "top_k": TOP_K,
        "cost_usd": 0,
    }


# ---------------------------------------------------------------------------- commands
def cmd_ingest(embedder, store) -> dict[str, Any]:
    t0 = time.perf_counter()
    pages, log = load_corpus(MANIFEST, ROOT)
    load_seconds = time.perf_counter() - t0
    if len(pages) < MIN_PAGES:
        raise ValueError(f"Only {len(pages)} content pages; need >= {MIN_PAGES}")
    log["load_seconds"] = round(load_seconds, 2)
    write_json(RESULTS / "ingest_log.json", log)

    stats: dict[str, Any] = {}
    for index in sorted({cfg["index"] for cfg in STRATEGIES.values()}):
        strategy = next(k for k, v in STRATEGIES.items() if v["index"] == index)
        t1 = time.perf_counter()
        chunks = build_chunks(pages, strategy)
        chunk_seconds = time.perf_counter() - t1

        t2 = time.perf_counter()
        sync = store.sync(index, chunks, embedder.embed_documents)
        embed_store_seconds = time.perf_counter() - t2

        tokens = embedder.count_tokens([c.text for c in chunks])
        truncated = sum(t > embedder.max_seq_length for t in tokens)
        stats[index] = {
            "used_by_strategies": [k for k, v in STRATEGIES.items() if v["index"] == index],
            "config": STRATEGIES[strategy]["params"],
            "chunk_count": len(chunks),
            "chars": length_stats([len(c.text) for c in chunks]),
            "tokens": length_stats(tokens),
            "chunks_over_max_seq_length": truncated,
            "context_prefixed_chunks": sum(bool(c.metadata.get("context_prefix")) for c in chunks),
            "chunk_seconds": round(chunk_seconds, 2),
            "embed_and_store_seconds": round(embed_store_seconds, 2),
            "sync": sync,
        }
        write_jsonl(RESULTS / "chunks" / f"chunks_{index}.jsonl",
                    [{"chunk_id": c.chunk_id, "document_id": c.document_id, "page": c.page,
                      "text": c.text, **c.metadata} for c in chunks])
        print(f"[ingest] index {index}: {len(chunks)} chunks, embedded {sync['embedded']}, "
              f"unchanged {sync['unchanged']}, deleted {sync['deleted_stale']}, rows {sync['rows_after']}, "
              f"{embed_store_seconds:.1f}s")

    record = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "pages": len(pages), "load_seconds": round(load_seconds, 2), "indexes": stats}
    history_path = RESULTS / "ingest_stats.json"
    history = json.loads(history_path.read_text(encoding="utf-8")).get("runs", []) if history_path.exists() else []
    write_json(history_path, {"latest": record, "runs": [*history, record]})
    write_json(RESULTS / "run_info.json", run_info(embedder, store))
    return record


def cmd_eval(embedder, store, split: str, frozen: bool) -> dict[str, Any]:
    if split in ("test", "all") and not frozen:
        sys.exit("Refusing to evaluate the test split without --frozen. Choose the strategy on dev "
                 "first (criteria in benchmark/README.md), then rerun with --frozen.")
    questions = [q for q in load_questions() if split == "all" or q["split"] == split]
    for index in {cfg["index"] for cfg in STRATEGIES.values()}:
        if store.count(index) == 0:
            sys.exit(f"Index {index} is empty. Run `python -m src.run ingest` first.")

    traces: list[dict[str, Any]] = []
    timings: dict[str, float] = {}
    query_vectors = {q["id"]: embedder.embed_query(q["question"]) for q in questions}
    for strategy, cfg in STRATEGIES.items():
        t0 = time.perf_counter()
        rows = []
        for q in questions:
            applied = q.get("filter") if cfg["use_filter"] else None
            hits = store.search(cfg["index"], query_vectors[q["id"]], top_k=TOP_K, filters=applied)
            trace = evaluate_query(q, hits)
            trace.update({"strategy": strategy, "index": cfg["index"], "applied_filter": applied})
            rows.append(trace)
        timings[strategy] = round(time.perf_counter() - t0, 3)
        write_jsonl(RESULTS / "traces" / f"{split}_{strategy}.jsonl", rows)
        traces.extend(rows)

    summary = summarize(traces)
    output = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "split": split, "search_seconds": timings, "summary": summary}
    write_json(RESULTS / f"summary_{split}.json", output)

    print(f"\n[eval] split={split}")
    print(f"{'Strategy':<9}{'Split':<6}{'Hit@1':>8}{'Hit@3':>8}{'GoldPg@3':>10}{'Filter@3':>10}  misses@3")
    for strategy, by_split in summary.items():
        for s, m in by_split.items():
            flt = m["filter_compliance_top3"]
            flt = flt["text"] if isinstance(flt, dict) else flt
            print(f"{strategy:<9}{s:<6}{m['hit@1']['text']:>8}{m['evidence_hit@3']['text']:>8}"
                  f"{m['gold_page_in_top3']['text']:>10}{flt:>10}  {','.join(m['misses_at_3']) or '-'}")
    if split in ("test", "all"):
        write_manual_templates(traces)
    return output


def write_manual_templates(traces: list[dict[str, Any]]) -> None:
    """CSV sheets for manual grounding labels and metadata audit on the test split."""
    test = [t for t in traces if t["split"] == "test"]
    grounding, metadata = [], []
    for t in test:
        row = {"strategy": t["strategy"], "question_id": t["id"], "question": t["question"],
               "expected_answer": t["expected_answer"], "applied_filter": json.dumps(t["applied_filter"], ensure_ascii=False),
               "auto_evidence_hit@3": t["hit@3"]}
        for h in t["hits"][:3]:
            row[f"top{h['rank']}_chunk"] = f"{h['chunk_id']}\n{h['text']}"
        row.update({"grounding_score_0_1_2": "", "reason": ""})
        grounding.append(row)
        for h in t["hits"][:3]:
            metadata.append({
                "strategy": t["strategy"], "question_id": t["id"], "rank": h["rank"],
                "chunk_id": h["chunk_id"], "source": h["source"], "page": h["page"],
                "law_name": h["law_name"], "chapters": ",".join(h["chapters"] or []),
                "articles": ",".join(h["articles"] or []), "text_excerpt": h["text"][:300],
                "question_filter": json.dumps(t["question_filter"], ensure_ascii=False),
                "auto_matches_filter": h["matches_question_filter"],
                "metadata_correct_Y_N": "", "error_note": "",
            })
    write_csv(RESULTS / "manual" / "grounding_labels.csv", grounding)
    write_csv(RESULTS / "manual" / "metadata_audit.csv", metadata)
    print("[eval] wrote results/manual/grounding_labels.csv and metadata_audit.csv for manual labelling")


def cmd_samples() -> None:
    """Pick 10 fixed source positions (evenly spaced pages, middle of the page) BEFORE scoring,
    and export the chunk covering each position for every strategy."""
    pages, _ = load_corpus(MANIFEST, ROOT)
    ordered = sorted(pages, key=lambda p: (p.document_id, p.page))
    picks = [ordered[round(i * (len(ordered) - 1) / 9)] for i in range(10)]
    chunks_by_index = {idx: build_chunks(picks, next(k for k, v in STRATEGIES.items() if v["index"] == idx))
                       for idx in {cfg["index"] for cfg in STRATEGIES.values()}}
    rows = []
    for n, page in enumerate(picks, start=1):
        position = len(page.text) // 2
        for strategy, cfg in STRATEGIES.items():
            covering = [c for c in chunks_by_index[cfg["index"]]
                        if c.document_id == page.document_id and c.page == page.page
                        and c.metadata["char_start"] <= position < c.metadata["char_end"]]
            chunk = covering[0] if covering else None
            rows.append({
                "position_id": f"pos{n:02d}", "page_id": f"{page.document_id}:p{page.page}",
                "char_position": position, "source_snippet": page.text[max(0, position - 60):position + 60].replace("\n", " "),
                "strategy": strategy, "chunk_id": chunk.chunk_id if chunk else "",
                "chunk_chars": len(chunk.text) if chunk else 0, "chunk_text": chunk.text if chunk else "",
                "coherence_score_0_1_2": "", "reason": "",
            })
    write_csv(RESULTS / "manual" / "coherence_labels.csv", rows)
    print(f"[samples] wrote results/manual/coherence_labels.csv ({len(rows)} rows; C shares B's chunks)")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Day 06 data ingestion pipeline")
    parser.add_argument("command", nargs="?", default="default",
                        choices=["default", "ingest", "eval", "samples"])
    parser.add_argument("--split", default="dev", choices=["dev", "test", "all"])
    parser.add_argument("--frozen", action="store_true",
                        help="confirm the strategy was chosen on dev before looking at test")
    args = parser.parse_args()

    if args.command == "samples":
        cmd_samples()
        return
    embedder, store = make_components()
    if args.command in ("default", "ingest"):
        cmd_ingest(embedder, store)
    if args.command in ("default", "eval"):
        cmd_eval(embedder, store, args.split, args.frozen)


if __name__ == "__main__":
    main()
