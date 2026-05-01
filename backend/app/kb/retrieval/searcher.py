from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.kb.ingestion.embedder import embed_text, vector_to_pgvector


async def search_kb(
    session: AsyncSession,
    client_id: str,
    query: str,
    domains: list[str],
    limit: int = 8,
    threshold: float = 0.05,
) -> list[dict]:
    if not domains:
        return []

    # Check if there are any entries to search before running vector query.
    # The hnsw index errors if the table is completely empty.
    count_result = await session.execute(
        text(
            """
            SELECT COUNT(*) FROM kb_entries e
            JOIN kb_domains d ON e.domain_id = d.id
            WHERE e.client_id = :client_id
              AND d.name = ANY(:domains)
              AND d.is_active = true
              AND e.embedding IS NOT NULL
            """
        ),
        {"client_id": client_id, "domains": domains},
    )
    if (count_result.scalar_one() or 0) == 0:
        return []

    query_vector = vector_to_pgvector(embed_text(query))
    result = await session.execute(
        text(
            """
            SELECT
                e.id,
                e.content,
                e.source_file,
                e.metadata,
                d.name AS domain,
                1 - (e.embedding <=> CAST(:query_vector AS vector)) AS similarity_score
            FROM kb_entries e
            JOIN kb_domains d ON e.domain_id = d.id
            WHERE e.client_id = :client_id
              AND d.name = ANY(:domains)
              AND d.is_active = true
              AND e.embedding IS NOT NULL
              AND 1 - (e.embedding <=> CAST(:query_vector AS vector)) >= :threshold
            ORDER BY e.embedding <=> CAST(:query_vector AS vector)
            LIMIT :limit
            """
        ),
        {
            "client_id": client_id,
            "query_vector": query_vector,
            "domains": domains,
            "threshold": threshold,
            "limit": limit,
        },
    )
    return [dict(row._mapping) for row in result]
