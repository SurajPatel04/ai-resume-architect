from functools import lru_cache

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

class AccessTokenSettings(BaseModel):
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    EXPIRE_MINUTES: int = 30

class RefreshTokenSettings(BaseModel):
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    EXPIRE_MINUTES: int = 30


class Settings(BaseSettings):
         
    APP_NAME: str = "AI Resume Architect"
    DEBUG: bool = False
                                                                   
    PUBLIC_BASE_URL: str = "http://localhost:8000"

              
    DATABASE_URL: str

         
    ACCESS_TOKEN: AccessTokenSettings
    REFRESH_TOKEN: RefreshTokenSettings

        
    OPENAI_API_KEY: str | None = None
    GEMINI_API_KEY: str | None = None

           
    REDIS_URL: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_nested_delimiter="__",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()