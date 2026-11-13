"""Day 06 Data Ingestion Engineering pipeline entry point."""
from __future__ import annotations

import json
import os
import statistics
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .chunking import by_paragraph, fixed_size
from .embeddings import MyEmbedder
from .evaluation import evaluate_query, summarize
from .ingestion import load_pdf_with_logs
from .models import Chunk, DocumentPage
from .store import PgVectorStore


def _chunk_stats(chunks: list[Chunk]) -> dict[str, Any]:
    lengths = [len(c.text) for c in chunks]
    return {
        "chunk_count": len(chunks),
        "total_chars": sum(lengths),
        "min_chars": min(lengths) if lengths else 0,
        "median_chars": int(statistics.median(lengths)) if lengths else 0,
        "mean_chars": round(statistics.mean(lengths), 1) if lengths else 0.0,
        "max_chars": max(lengths) if lengths else 0,
    }


def main() -> None:
    starter_dir = Path(__file__).resolve().parents[1]
    repo_root = starter_dir.parent
    load_dotenv(starter_dir / ".env")

    database_url = os.getenv("DATABASE_URL", "")
    model_name = os.getenv("EMBEDDING_MODEL") or "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

    corpus_pdf = starter_dir / "data" / "nd_168_2024.pdf"
    benchmark_path = repo_root / "benchmark" / "questions.json"
    results_dir = starter_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    # 1. Load corpus and validate >= 30 valid content pages
    pages, page_logs = load_pdf_with_logs(
        path=corpus_pdf,
        document_id="nd-168-2024",
        source="starter/data/nd_168_2024.pdf",
        base_metadata={"year": 2024, "document_type": "nghi_dinh", "language": "vi"},
    )
    if len(pages) < 30:
        raise RuntimeError(f"Corpus must have >= 30 valid content pages, got {len(pages)}")

    questions: list[dict[str, Any]] = json.loads(benchmark_path.read_text(encoding="utf-8"))
    print(f"Loaded {len(pages)} valid pages ({sum(len(p.text) for p in pages)} chars), {len(page_logs)} error/empty pages.")
    print(f"Loaded {len(questions)} benchmark questions.")

    # 2. Initialize real embedder & PostgreSQL + pgvector store
    embedder = MyEmbedder(model_name=model_name)
    store = PgVectorStore(database_url=database_url, dimensions=embedder.dimensions)
    store.create_schema()

    # 3. Build chunks for strategies A, B, C
    # Note: B and C share identical chunking (by_paragraph, max_size=700);
    # only retrieval-time metadata filtering differs between B and C.
    chunks_a: list[Chunk] = []
    chunks_b: list[Chunk] = []
    chunks_c: list[Chunk] = []
    for p in pages:
        chunks_a.extend(fixed_size(p, size=500, overlap=50, strategy_tag="A"))
        chunks_b.extend(by_paragraph(p, max_size=700, overlap=80, strategy_tag="B"))
        chunks_c.extend(by_paragraph(p, max_size=700, overlap=80, strategy_tag="C"))

    strategy_chunks = {
        "A": chunks_a,
        "B": chunks_b,
        "C": chunks_c,
    }

    # 4. Embed & ingest each strategy (plus idempotency check on A)
    ingestion_stats: dict[str, Any] = {
        "embedding_model": embedder.model_name,
        "dimensions": embedder.dimensions,
        "valid_pages": len(pages),
        "page_logs": page_logs,
        "cost_usd": 0.0,
        "strategies": {},
    }

    for strat, chunks in strategy_chunks.items():
        t0 = time.perf_counter()
        vectors = embedder.embed_documents([c.text for c in chunks])
        store.upsert(strategy=strat, chunks=chunks, vectors=vectors)
        elapsed = round(time.perf_counter() - t0, 3)

        stats = _chunk_stats(chunks)
        stats["ingest_seconds"] = elapsed
        stats["db_count_after_ingest"] = store.count_chunks(strat)

        # Idempotency check: re-upsert first 5 chunks of strategy A and verify count unchanged
        if strat == "A":
            before = store.count_chunks("A")
            store.upsert(strategy="A", chunks=chunks, vectors=vectors)
            after = store.count_chunks("A")
            stats["reingest_count_before"] = before
            stats["reingest_count_after"] = after
            stats["idempotent_no_duplicates"] = (before == after)

        ingestion_stats["strategies"][strat] = stats
        print(f"Strategy {strat}: {stats['chunk_count']} chunks ingested in {elapsed}s (DB rows={stats['db_count_after_ingest']})")

    # 5. Run benchmark queries across A, B, C
    query_vectors = {q["id"]: embedder.embed_query(q["question"]) for q in questions}
    all_traces: list[dict[str, Any]] = []

    for strat in ["A", "B", "C"]:
        t0 = time.perf_counter()
        for q in questions:
            applied_filter = q.get("filter") if strat == "C" else None
            hits = store.search(
                strategy=strat,
                query_vector=query_vectors[q["id"]],
                top_k=3,
                filters=applied_filter,
            )
            trace = evaluate_query(q, hits, strategy=strat, applied_filter=applied_filter)
            all_traces.append(trace)
        ingestion_stats["strategies"][strat]["query_seconds"] = round(time.perf_counter() - t0, 3)

    summary = summarize(all_traces)

    # 6. Save traces, summary, and ingestion stats
    (results_dir / "traces.json").write_text(json.dumps(all_traces, ensure_ascii=False, indent=2), encoding="utf-8")
    (results_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (results_dir / "ingestion_stats.json").write_text(json.dumps(ingestion_stats, ensure_ascii=False, indent=2), encoding="utf-8")

    # Prepare deterministic coherence sample (first 10 pages) for manual assessment
    sample_pages = [1, 2, 3, 6, 7, 8, 9, 10, 15, 18]
    coherence_samples: dict[str, Any] = {}
    for p_num in sample_pages:
        coherence_samples[str(p_num)] = {
            strat: [
                {"chunk_id": c.chunk_id, "text": c.text}
                for c in strategy_chunks[strat]
                if c.page == p_num
            ][:2]
            for strat in ["A", "B", "C"]
        }
    (results_dir / "coherence_samples.json").write_text(
        json.dumps(coherence_samples, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n=== SUMMARY ===")
    for k, v in summary.items():
        print(
            f"{k}: Hit@1={v['hit_at_1_count']}/{v['n_questions']} ({v['hit_at_1_rate']:.2%}) | "
            f"Hit@3={v['evidence_hit_at_3_count']}/{v['n_questions']} ({v['evidence_hit_at_3_rate']:.2%})"
        )


if __name__ == "__main__":
    main()
