import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class BaseSchema(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

class SignUpRequest(BaseSchema):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)


class SignInRequest(BaseSchema):
    email: EmailStr
    password: str

class UserResponse(BaseSchema):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    id: uuid.UUID
    first_name: str
    last_name: str
    email: EmailStr
    created_at: datetime