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
    account_status: str = Field(alias="accountStatus")  # active, suspended, deleted
    created_at: datetime = Field(alias="createdAt")

    model_config = {"from_attributes": True, "populate_by_name": True}


class LoginResponse(BaseModel):
    access_token: str = Field(alias="accessToken")
    refresh_token: str = Field(alias="refreshToken")
    user: UserResponse

    model_config = {"populate_by_name": True}


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