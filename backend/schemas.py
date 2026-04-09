from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime


class UserRegister(BaseModel):
    email: EmailStr
    password: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str


class UserOut(BaseModel):
    id: int
    email: str
    is_approved: bool
    is_admin: bool
    custom_prompt: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class UserSettingsUpdate(BaseModel):
    custom_prompt: Optional[str] = None


class GenerateRequest(BaseModel):
    input_text: str


class GenerationOut(BaseModel):
    id: int
    input_text: str
    params_json: Optional[str] = None
    scad_code: Optional[str] = None
    stl_url: Optional[str] = None
    status: str
    error_message: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class SystemPromptOut(BaseModel):
    id: int
    name: str
    content: str
    updated_at: datetime

    model_config = {"from_attributes": True}


class SystemPromptUpdate(BaseModel):
    content: str
