"""Pydantic schemas for auth endpoints — matching 05-openapi.yaml."""

from datetime import datetime
from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: str
    email: str
    account_status: str  # active, suspended, deleted
    created_at: datetime

    model_config = {"from_attributes": True}


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    user: UserResponse


class ErrorDetail(BaseModel):
    field: str | None = None
    reason: str | None = None
    allowed: list[str] | None = None


class ErrorResponse(BaseModel):
    status: int
    code: str
    message: str
    timestamp: datetime
    path: str
    details: ErrorDetail | None = None