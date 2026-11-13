"""Store and search vectors in PostgreSQL + pgvector (exact cosine search, no ANN index)."""
import json
from typing import Any, Callable

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

from .models import Chunk

# Dedicated table name: the shared lab database already contains an unrelated "chunks" table.
TABLE = "law_chunks"
# Whitelisted metadata filters -> parameterized SQL. Values are always bound, never formatted.
FILTER_SQL = {
    "law_name": "law_name = %s",
    "document_id": "document_id = %s",
    "chapter": "%s = ANY(chapters)",
}


class PgVectorStore:
    def __init__(self, database_url: str, dimensions: int, embedding_model: str = "") -> None:
        if not database_url:
            raise ValueError("DATABASE_URL is empty")
        if not isinstance(dimensions, int) or dimensions <= 0:
            raise ValueError(f"Invalid embedding dimensions: {dimensions!r}")
        self.database_url = database_url
        self.dimensions = dimensions
        self.embedding_model = embedding_model

    def _connect(self) -> psycopg.Connection:
        connection = psycopg.connect(self.database_url, connect_timeout=5)
        register_vector(connection)
        return connection

    def create_schema(self) -> None:
        """Create the table (vector column + source/page/filter metadata); verify dimensions."""
        with self._connect() as conn:
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {TABLE} (
                    strategy        text NOT NULL,
                    chunk_id        text NOT NULL,
                    document_id     text NOT NULL,
                    source          text NOT NULL,
                    page            integer NOT NULL,
                    law_name        text,
                    chapters        text[] NOT NULL DEFAULT '{{}}',
                    articles        text[] NOT NULL DEFAULT '{{}}',
                    text            text NOT NULL,
                    content_hash    text NOT NULL,
                    metadata        jsonb NOT NULL DEFAULT '{{}}',
                    embedding_model text NOT NULL,
                    embedding       vector({int(self.dimensions)}) NOT NULL,
                    ingested_at     timestamptz NOT NULL DEFAULT now(),
                    PRIMARY KEY (strategy, chunk_id)
                )""")
            conn.execute(f"CREATE INDEX IF NOT EXISTS {TABLE}_strategy_law_idx ON {TABLE} (strategy, law_name)")
            row = conn.execute(
                "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                "WHERE attrelid = %s::regclass AND attname = 'embedding'", (TABLE,)).fetchone()
        if row[0] != f"vector({self.dimensions})":
            raise RuntimeError(f"Existing column is {row[0]} but the model has {self.dimensions} "
                               "dimensions. Use a new table/database instead of mixing models.")

    def existing(self, strategy: str) -> dict[str, tuple[str, str]]:
        """chunk_id -> (content_hash, embedding_model) currently stored for a strategy."""
        with self._connect() as conn:
            rows = conn.execute(f"SELECT chunk_id, content_hash, embedding_model FROM {TABLE} "
                                "WHERE strategy = %s", (strategy,)).fetchall()
        return {r[0]: (r[1], r[2]) for r in rows}

    def upsert(self, strategy: str, chunks: list[Chunk], vectors: list[list[float]],
               prune_documents: bool = True) -> None:
        """Validate, then insert/update by stable (strategy, chunk_id) so re-ingest never duplicates.

        With prune_documents=True, `chunks` is treated as the complete set for its documents and
        stale chunks of those documents (e.g. after a source changed) are deleted.
        """
        if len(chunks) != len(vectors):
            raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
        ids = [c.chunk_id for c in chunks]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate chunk_id in batch")
        for chunk, vector in zip(chunks, vectors):
            if len(vector) != self.dimensions:
                raise ValueError(f"{chunk.chunk_id}: vector has {len(vector)} dims, expected {self.dimensions}")
        rows = [(
            strategy, c.chunk_id, c.document_id, c.source, c.page,
            c.metadata.get("law_name"), c.metadata.get("chapters", []), c.metadata.get("articles", []),
            c.text, c.metadata["content_hash"], json.dumps(c.metadata, ensure_ascii=False),
            self.embedding_model, np.asarray(v, dtype=np.float32),
        ) for c, v in zip(chunks, vectors)]
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.executemany(f"""
                    INSERT INTO {TABLE} (strategy, chunk_id, document_id, source, page, law_name,
                        chapters, articles, text, content_hash, metadata, embedding_model, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (strategy, chunk_id) DO UPDATE SET
                        document_id = EXCLUDED.document_id, source = EXCLUDED.source,
                        page = EXCLUDED.page, law_name = EXCLUDED.law_name,
                        chapters = EXCLUDED.chapters, articles = EXCLUDED.articles,
                        text = EXCLUDED.text, content_hash = EXCLUDED.content_hash,
                        metadata = EXCLUDED.metadata, embedding_model = EXCLUDED.embedding_model,
                        embedding = EXCLUDED.embedding, ingested_at = now()""", rows)
                if prune_documents:
                    self._prune(cur, strategy, {c.document_id for c in chunks}, ids)

    @staticmethod
    def _prune(cur, strategy: str, document_ids: set[str], keep_ids: list[str]) -> int:
        cur.execute(f"DELETE FROM {TABLE} WHERE strategy = %s AND document_id = ANY(%s) "
                    "AND NOT (chunk_id = ANY(%s))", (strategy, list(document_ids), keep_ids))
        return cur.rowcount

    def sync(self, strategy: str, chunks: list[Chunk],
             embed: Callable[[list[str]], list[list[float]]]) -> dict[str, int]:
        """Incremental ingest: embed only new/changed chunks, upsert them, delete stale ones."""
        stored = self.existing(strategy)
        changed = [c for c in chunks
                   if stored.get(c.chunk_id) != (c.metadata["content_hash"], self.embedding_model)]
        vectors = embed([c.text for c in changed]) if changed else []
        if changed:
            self.upsert(strategy, changed, vectors, prune_documents=False)
        with self._connect() as conn, conn.cursor() as cur:
            removed = self._prune(cur, strategy, {c.document_id for c in chunks}, [c.chunk_id for c in chunks])
        return {"input_chunks": len(chunks), "embedded": len(changed),
                "unchanged": len(chunks) - len(changed), "deleted_stale": removed,
                "rows_after": self.count(strategy)}

    def count(self, strategy: str) -> int:
        with self._connect() as conn:
            return conn.execute(f"SELECT count(*) FROM {TABLE} WHERE strategy = %s", (strategy,)).fetchone()[0]

    def search(self, strategy: str, query_vector: list[float], top_k: int = 3,
               filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Filter in SQL, rank by cosine distance (<=>), return top-k with score = 1 - distance."""
        if len(query_vector) != self.dimensions:
            raise ValueError(f"Query vector has {len(query_vector)} dims, expected {self.dimensions}")
        where, params = ["strategy = %s"], [strategy]
        for key, value in (filters or {}).items():
            if key not in FILTER_SQL:
                raise ValueError(f"Unsupported filter field: {key}")
            where.append(FILTER_SQL[key])
            params.append(value)
        vector = np.asarray(query_vector, dtype=np.float32)
        sql = (f"SELECT chunk_id, document_id, source, page, law_name, chapters, articles, text, "
               f"metadata, 1 - (embedding <=> %s) AS score FROM {TABLE} "
               f"WHERE {' AND '.join(where)} ORDER BY embedding <=> %s LIMIT %s")
        with self._connect() as conn:
            rows = conn.execute(sql, [vector, *params, vector, int(top_k)]).fetchall()
        keys = ["chunk_id", "document_id", "source", "page", "law_name", "chapters", "articles",
                "text", "metadata", "score"]
        return [{**dict(zip(keys, row)), "score": round(float(row[-1]), 6)} for row in rows]

    def server_info(self) -> dict[str, str]:
        with self._connect() as conn:
            pg = conn.execute("SELECT current_setting('server_version')").fetchone()[0]
            ext = conn.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'").fetchone()[0]
        return {"postgresql": pg, "pgvector": ext, "table": TABLE,
                "search": "exact (sequential scan, no ANN index), cosine distance <=>"}
