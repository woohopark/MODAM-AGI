from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MODAM_", env_file=(".local/runtime.env", ".env"), extra="ignore"
    )

    database_url: str = Field(default="sqlite:///./modam.db", repr=False)
    session_ttl_seconds: int = Field(default=3600, ge=60, le=86400)
    groq_model: str = "llama-3.3-70b-versatile"
    groq_timeout_seconds: float = Field(default=30, ge=1, le=120)
    groq_api_key: SecretStr = Field(default=SecretStr(""), validation_alias="GROQ_API_KEY")
