import asyncio
import json
import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import get_current_user, require_roles
from app.database import get_db_session
from app.services.llm import get_llm, get_llm_config
from app.kb.ingestion.embedder import embed_text, vector_to_pgvector
from app.kb.ingestion.pipeline import document_to_chunks
from app.kb.retrieval.query_router import resolve_domains
from app.kb.retrieval.searcher import search_kb
from app.kb.schemas import (
    IngestionRead,
    KBDomainCreate,
    KBDomainRead,
    KBDomainUpdate,
    KBSearchResponse,
    KBSearchResult,
)
from app.models import User, UserRole
from app.services.clients import get_request_client_id

router = APIRouter(prefix="/kb", tags=["knowledge-base"])


@router.get("/domains", response_model=list[KBDomainRead])
async def list_domains(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[KBDomainRead]:
    client_id = await get_request_client_id(session, current_user)
    result = await session.execute(
        text(
            """
            SELECT id, client_id, name, description, is_active, created_at
            FROM kb_domains
            WHERE client_id = :client_id
            ORDER BY name
            """
        ),
        {"client_id": client_id},
    )
    return [KBDomainRead(**dict(row._mapping)) for row in result]


@router.post("/domains", response_model=KBDomainRead, status_code=status.HTTP_201_CREATED)
async def create_domain(
    payload: KBDomainCreate,
    current_user: Annotated[User, Depends(require_roles(UserRole.admin, UserRole.executive))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> KBDomainRead:
    client_id = await get_request_client_id(session, current_user)
    try:
        result = await session.execute(
            text(
                """
                INSERT INTO kb_domains (client_id, name, description)
                VALUES (:client_id, :name, :description)
                RETURNING id, client_id, name, description, is_active, created_at
                """
            ),
            {"client_id": client_id, "name": payload.name, "description": payload.description},
        )
        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Could not create domain: {exc}",
        ) from exc
    return KBDomainRead(**dict(result.one()._mapping))


@router.patch("/domains/{domain_id}", response_model=KBDomainRead)
async def update_domain(
    domain_id: UUID,
    payload: KBDomainUpdate,
    current_user: Annotated[User, Depends(require_roles(UserRole.admin, UserRole.executive))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> KBDomainRead:
    client_id = await get_request_client_id(session, current_user)
    existing = await session.execute(
        text(
            """
            SELECT id FROM kb_domains
            WHERE id = :domain_id AND client_id = :client_id
            """
        ),
        {"domain_id": str(domain_id), "client_id": client_id},
    )
    if existing.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Domain not found")

    values = payload.model_dump(exclude_unset=True)
    merged = {
        "domain_id": str(domain_id),
        "client_id": client_id,
        "name": values.get("name"),
        "description": values.get("description"),
        "is_active": values.get("is_active"),
    }
    result = await session.execute(
        text(
            """
            UPDATE kb_domains
            SET
                name = COALESCE(:name, name),
                description = COALESCE(:description, description),
                is_active = COALESCE(:is_active, is_active),
                updated_at = now()
            WHERE id = :domain_id AND client_id = :client_id
            RETURNING id, client_id, name, description, is_active, created_at
            """
        ),
        merged,
    )
    await session.commit()
    return KBDomainRead(**dict(result.one()._mapping))


@router.post("/ingest", response_model=IngestionRead, status_code=status.HTTP_201_CREATED)
async def ingest_document(
    current_user: Annotated[User, Depends(require_roles(UserRole.admin, UserRole.executive))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    file: UploadFile = File(...),
    domain_id: UUID = Form(...),
    metadata: str | None = Form(default=None),
) -> IngestionRead:
    client_id = await get_request_client_id(session, current_user)
    file_bytes = await file.read()
    filename = file.filename or "uploaded-file"
    parsed_metadata = _parse_metadata(metadata)

    domain_exists = await session.execute(
        text(
            """
            SELECT id FROM kb_domains
            WHERE id = :domain_id AND client_id = :client_id AND is_active = true
            """
        ),
        {"domain_id": str(domain_id), "client_id": client_id},
    )
    if domain_exists.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Active domain not found")

    ingestion_id = await _create_ingestion_log(
        session=session,
        client_id=client_id,
        domain_id=str(domain_id),
        filename=filename,
        file_type=None,
        status="processing",
    )

    try:
        file_type, chunks = document_to_chunks(filename, file_bytes)
        for index, chunk in enumerate(chunks):
            vector = vector_to_pgvector(embed_text(chunk))
            await session.execute(
                text(
                    """
                    INSERT INTO kb_entries (
                        client_id, domain_id, source_file, chunk_index,
                        content, embedding, embedding_model, metadata
                    )
                    VALUES (
                        :client_id, :domain_id, :source_file, :chunk_index,
                        :content, CAST(:embedding AS vector), :embedding_model, CAST(:metadata AS jsonb)
                    )
                    """
                ),
                {
                    "client_id": client_id,
                    "domain_id": str(domain_id),
                    "source_file": filename,
                    "chunk_index": index,
                    "content": chunk,
                    "embedding": vector,
                    "embedding_model": "local-hashing-768",
                    "metadata": json.dumps(parsed_metadata),
                },
            )
        await _complete_ingestion_log(session, ingestion_id, file_type, len(chunks))
        await session.commit()
    except Exception as exc:
        await session.rollback()
        await _mark_ingestion_failed(
            session=session,
            ingestion_id=ingestion_id,
            error_detail=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ingestion failed: {exc}",
        ) from exc

    return await _get_ingestion_log(session, ingestion_id)


@router.get("/search", response_model=KBSearchResponse)
async def search(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    q: str = Query(..., min_length=1),
    domain: list[str] | None = Query(default=None),
    limit: int = Query(default=8, ge=1, le=25),
    threshold: float = Query(default=0.05, ge=-1.0, le=1.0),
) -> KBSearchResponse:
    client_id = await get_request_client_id(session, current_user)
    domains = await resolve_domains(session, client_id, domain)
    rows = await search_kb(session, client_id, q, domains, limit=limit, threshold=threshold)
    return KBSearchResponse(
        query=q,
        domains_searched=domains,
        results=[KBSearchResult(**row) for row in rows],
    )


def _parse_metadata(metadata: str | None) -> dict:
    if not metadata:
        return {}
    try:
        parsed = json.loads(metadata)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="metadata must be valid JSON",
        ) from exc
    if not isinstance(parsed, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="metadata must be a JSON object",
        )
    return parsed


async def _create_ingestion_log(
    session: AsyncSession,
    client_id: str,
    domain_id: str,
    filename: str,
    file_type: str | None,
    status: str,
) -> str:
    result = await session.execute(
        text(
            """
            INSERT INTO kb_ingestion_log (client_id, domain_id, filename, file_type, status)
            VALUES (:client_id, :domain_id, :filename, :file_type, :status)
            RETURNING id
            """
        ),
        {
            "client_id": client_id,
            "domain_id": domain_id,
            "filename": filename,
            "file_type": file_type,
            "status": status,
        },
    )
    await session.commit()
    return str(result.scalar_one())


async def _complete_ingestion_log(
    session: AsyncSession,
    ingestion_id: str,
    file_type: str,
    chunks_created: int,
) -> None:
    await session.execute(
        text(
            """
            UPDATE kb_ingestion_log
            SET file_type = :file_type, chunks_created = :chunks_created, status = 'complete'
            WHERE id = :ingestion_id
            """
        ),
        {
            "ingestion_id": ingestion_id,
            "file_type": file_type,
            "chunks_created": chunks_created,
        },
    )


async def _mark_ingestion_failed(
    session: AsyncSession,
    ingestion_id: str,
    error_detail: str,
) -> None:
    await session.execute(
        text(
            """
            UPDATE kb_ingestion_log
            SET status = 'failed', error_detail = :error_detail
            WHERE id = :ingestion_id
            """
        ),
        {"ingestion_id": ingestion_id, "error_detail": error_detail},
    )
    await session.commit()


async def _get_ingestion_log(session: AsyncSession, ingestion_id: str) -> IngestionRead:
    result = await session.execute(
        text(
            """
            SELECT id, client_id, domain_id, filename, file_type,
                   chunks_created, status, error_detail, ingested_at
            FROM kb_ingestion_log
            WHERE id = :ingestion_id
            """
        ),
        {"ingestion_id": ingestion_id},
    )
    return IngestionRead(**dict(result.one()._mapping))


# ─── INDUSTRY DETECTION ────────────────────────────────────────────────────────

@router.get("/industry")
async def detect_industry(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict:
    """
    Read KB entries for this client and use the LLM to infer the company's industry,
    sector, and relevant business context.
    """
    client_id = await get_request_client_id(session, current_user)

    # Pull up to 12 diverse KB chunks (ordered by domain + entry to sample variety)
    result = await session.execute(
        text(
            """
            SELECT ke.content, kd.name AS domain_name
            FROM kb_entries ke
            LEFT JOIN kb_domains kd ON ke.domain_id = kd.id
            WHERE ke.client_id = :client_id
            ORDER BY kd.name, ke.chunk_index
            LIMIT 12
            """
        ),
        {"client_id": client_id},
    )
    rows = result.all()

    if not rows:
        return {
            "industry": "Unknown",
            "sector": "Unknown",
            "confidence": 0.0,
            "indicators": [],
            "company_size": "Unknown",
            "reasoning": "No Knowledge Base documents uploaded yet. Upload company documents to enable industry detection.",
            "detected": False,
        }

    # Build context from KB excerpts
    excerpts = "\n\n".join(
        f"[Domain: {r.domain_name}]\n{r.content[:600]}"
        for r in rows
    )

    system_prompt = (
        "You are a senior business analyst specialising in company classification. "
        "Analyse the provided document excerpts from a company's internal Knowledge Base "
        "and accurately identify the industry and sector. "
        "Be specific — do not default to generic categories if the evidence supports precision. "
        "Always respond with valid JSON only, no markdown, no explanation outside the JSON."
    )

    user_prompt = f"""Analyse these Knowledge Base document excerpts and identify the company's industry profile.

DOCUMENT EXCERPTS:
{excerpts}

Respond with this exact JSON structure:
{{
  "industry": "e.g. Financial Services",
  "sector": "e.g. Corporate Finance & Investment",
  "confidence": 0.85,
  "indicators": ["specific phrase or term from docs that indicates industry", "another indicator"],
  "company_size": "SME or Enterprise",
  "reasoning": "2-3 sentence explanation of how you determined this industry from the documents"
}}"""

    try:
        config = get_llm_config("orchestrator")
        client_llm = get_llm("orchestrator")
        response = await client_llm.chat.completions.create(
            model=config.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=600,
            temperature=0.1,
        )
        raw = response.choices[0].message.content or ""
        raw = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
        match = re.search(r"\{[\s\S]*\}", raw)
        if not match:
            raise ValueError("No JSON in response")
        data = json.loads(match.group())
        data["detected"] = True
        return data
    except Exception as exc:
        return {
            "industry": "Unable to determine",
            "sector": "Unknown",
            "confidence": 0.0,
            "indicators": [],
            "company_size": "Unknown",
            "reasoning": f"Detection failed: {exc}",
            "detected": False,
        }
