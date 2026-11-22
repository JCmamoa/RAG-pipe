import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

Role = Literal["admin", "member"]


class RegisterIn(BaseModel):
    org_name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    email: EmailStr
    role: Role
    is_active: bool


class UserCreateIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: Role = "member"


class UserUpdateIn(BaseModel):
    role: Role | None = None
    is_active: bool | None = None


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    status: str
    error: str | None
    size_bytes: int
    page_count: int | None
    uploaded_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class UploadRequestIn(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0)


class UploadFormOut(BaseModel):
    url: str
    fields: dict[str, str]


class UploadTicketOut(BaseModel):
    document: DocumentOut
    upload: UploadFormOut


class SearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    k: int = Field(default=6, ge=1, le=20)
    document_ids: list[uuid.UUID] | None = None


class SearchHitOut(BaseModel):
    chunk_id: int
    document_id: uuid.UUID
    filename: str
    page: int | None
    chunk_index: int
    content: str
    score: float
