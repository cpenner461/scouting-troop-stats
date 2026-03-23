"""Pydantic request/response models."""

from pydantic import BaseModel, EmailStr


class RegisterRequest(BaseModel):
    email: EmailStr
    display_name: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class ResetPasswordRequest(BaseModel):
    email: str


class ResetPasswordConfirm(BaseModel):
    token: str
    new_password: str


class CreateTroopRequest(BaseModel):
    name: str
    db_filename: str


class JoinTroopRequest(BaseModel):
    troop_id: int


class QueryRequest(BaseModel):
    sql: str
    params: list = []


class UserResponse(BaseModel):
    id: int
    email: str
    display_name: str
    troop: dict | None = None


class TroopResponse(BaseModel):
    id: int
    name: str


class MemberResponse(BaseModel):
    user_id: int
    email: str
    display_name: str
    status: str
    joined_at: str
