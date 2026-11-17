import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .models import AssetKind, DocumentStatus, UserStatus


class SignInRequest(BaseModel):
    key: str = Field(min_length=8, max_length=200)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    display_name: str
    status: UserStatus
    created_at: datetime


class SessionInfo(BaseModel):
    user: UserOut
    session_expires_at: datetime
    key_expires_at: datetime


class AdminCreateUserRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)


class AdminUserPatchRequest(BaseModel):
    status: UserStatus


class KeyIssueRequest(BaseModel):
    expires_at: datetime | None = None


class KeyMetadata(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key_prefix: str
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime
    last_used_at: datetime | None


class IssuedKeyOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    key: str
    key_prefix: str
    expires_at: datetime


class AdminUserOut(UserOut):
    keys: list[KeyMetadata]


class AdminUserList(BaseModel):
    users: list[AdminUserOut]


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    file_name: str
    file_size_bytes: int
    page_count: int | None
    status: DocumentStatus
    failure_reason: str | None
    created_at: datetime
    processed_at: datetime | None


class UploadResponse(BaseModel):
    document_id: uuid.UUID
    status: DocumentStatus
    message: str


class DocumentAssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    page_number: int
    kind: AssetKind
    asset_index: int
    mime_type: str
    width: int
    height: int
    caption: str | None
    content_path: str


class SearchResult(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    section_title: str | None
    page_start: int
    page_end: int
    snippet: str
    score: float


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]


class ExplanationRequest(BaseModel):
    chunk_id: uuid.UUID
    question: str | None = Field(default=None, max_length=500)


class CitationOut(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    page_start: int
    page_end: int
    excerpt: str


class ExplanationResponse(BaseModel):
    explanation_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    section_title: str | None
    page_start: int
    page_end: int
    answer: str
    citations: list[CitationOut]
    insufficient_context: bool
    model: str
