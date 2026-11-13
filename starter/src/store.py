"""Store and search vectors using PostgreSQL + pgvector."""
from __future__ import annotations

import json
from typing import Any

import psycopg

from .models import Chunk

ALLOWED_FILTER_KEYS = {
    "document_id",
    "chapter",
    "section",
    "year",
    "category",
    "audience",
    "language",
    "document_type",
}


def _to_pgvector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"


class PgVectorStore:
    def __init__(self, database_url: str, dimensions: int) -> None:
        if not database_url:
            raise ValueError("database_url must not be empty")
        if dimensions <= 0:
            raise ValueError("dimensions must be > 0")
        self.database_url = database_url
        self.dimensions = dimensions

    def create_schema(self) -> None:
        """Create table with vector column and source/page/filter metadata."""
        ddl = f"""
        CREATE TABLE IF NOT EXISTS document_chunks (
            chunk_id TEXT PRIMARY KEY,
            strategy TEXT NOT NULL,
            document_id TEXT NOT NULL,
            source TEXT NOT NULL,
            page INTEGER NOT NULL,
            text TEXT NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            embedding vector({self.dimensions}) NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_document_chunks_strategy_doc
            ON document_chunks (strategy, document_id);
        CREATE INDEX IF NOT EXISTS idx_document_chunks_metadata_gin
            ON document_chunks USING GIN (metadata);
        """
        with psycopg.connect(self.database_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute(ddl)
            conn.commit()

    def count_chunks(self, strategy: str | None = None) -> int:
        with psycopg.connect(self.database_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                if strategy is None:
                    cur.execute("SELECT COUNT(*) FROM document_chunks")
                else:
                    cur.execute("SELECT COUNT(*) FROM document_chunks WHERE strategy = %s", (strategy,))
                row = cur.fetchone()
                return int(row[0]) if row else 0

    def upsert(self, strategy: str, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        """Validate lengths/dimensions, remove obsolete chunks, and upsert without duplicates."""
        if len(chunks) != len(vectors):
            raise ValueError(f"chunks ({len(chunks)}) and vectors ({len(vectors)}) length mismatch")
        for i, vec in enumerate(vectors):
            if len(vec) != self.dimensions:
                raise ValueError(f"Vector {i} has dimension {len(vec)}, expected {self.dimensions}")

        if not chunks:
            return

        doc_ids = sorted({c.document_id for c in chunks})
        new_ids = [c.chunk_id for c in chunks]

        upsert_sql = """
        INSERT INTO document_chunks (chunk_id, strategy, document_id, source, page, text, metadata, embedding)
        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::vector)
        ON CONFLICT (chunk_id) DO UPDATE SET
            strategy = EXCLUDED.strategy,
            document_id = EXCLUDED.document_id,
            source = EXCLUDED.source,
            page = EXCLUDED.page,
            text = EXCLUDED.text,
            metadata = EXCLUDED.metadata,
            embedding = EXCLUDED.embedding,
            updated_at = NOW();
        """

        with psycopg.connect(self.database_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                for doc_id in doc_ids:
                    cur.execute(
                        "DELETE FROM document_chunks WHERE strategy = %s AND document_id = %s AND NOT (chunk_id = ANY(%s))",
                        (strategy, doc_id, new_ids),
                    )
                for chunk, vec in zip(chunks, vectors):
                    cur.execute(
                        upsert_sql,
                        (
                            chunk.chunk_id,
                            strategy,
                            chunk.document_id,
                            chunk.source,
                            chunk.page,
                            chunk.text,
                            json.dumps(chunk.metadata, ensure_ascii=False),
                            _to_pgvector_literal(vec),
                        ),
                    )
            conn.commit()

    def search(
        self,
        strategy: str,
        query_vector: list[float],
        top_k: int = 3,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Filter permitted metadata in SQL, rank by cosine distance, return top-k."""
        if len(query_vector) != self.dimensions:
            raise ValueError(f"Query vector dimension {len(query_vector)} != {self.dimensions}")

        where_clauses = ["strategy = %s"]
        params: list[Any] = [strategy]

        if filters:
            clean_filters: dict[str, Any] = {}
            for k, v in filters.items():
                if k not in ALLOWED_FILTER_KEYS:
                    raise ValueError(f"Unsupported metadata filter key: {k}")
                clean_filters[k] = v
            if clean_filters:
                where_clauses.append("metadata @> %s::jsonb")
                params.append(json.dumps(clean_filters, ensure_ascii=False))

        vec_lit = _to_pgvector_literal(query_vector)
        sql = f"""
        SELECT
            chunk_id,
            document_id,
            source,
            page,
            text,
            metadata,
            1.0 - (embedding <=> %s::vector) AS cosine_similarity
        FROM document_chunks
        WHERE {' AND '.join(where_clauses)}
        ORDER BY embedding <=> %s::vector ASC
        LIMIT %s;
        """
        query_params = [vec_lit, *params, vec_lit, top_k]

        results: list[dict[str, Any]] = []
        with psycopg.connect(self.database_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, query_params)
                for row in cur.fetchall():
                    results.append(
                        {
                            "chunk_id": row[0],
                            "document_id": row[1],
                            "source": row[2],
                            "page": int(row[3]),
                            "text": row[4],
                            "metadata": row[5] if isinstance(row[5], dict) else json.loads(row[5]),
                            "score": float(row[6]),
                        }
                    )
        return results
