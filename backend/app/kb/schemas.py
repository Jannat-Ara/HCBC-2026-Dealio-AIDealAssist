from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class KBDomainCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None


class KBDomainUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    is_active: bool | None = None


class KBDomainRead(BaseModel):
    id: UUID
    client_id: UUID
    name: str
    description: str | None
    is_active: bool
    created_at: datetime


class IngestionRead(BaseModel):
    id: UUID
    client_id: UUID
    domain_id: UUID | None
    filename: str | None
    file_type: str | None
    chunks_created: int
    status: str
    error_detail: str | None
    ingested_at: datetime


class KBSearchResult(BaseModel):
    id: UUID
    content: str
    source_file: str | None
    metadata: dict
    domain: str
    similarity_score: float


class KBSearchResponse(BaseModel):
    query: str
    domains_searched: list[str]
    results: list[KBSearchResult]
