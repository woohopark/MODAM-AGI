from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MODAM_", extra="ignore")

    database_url: SecretStr = SecretStr("postgresql+psycopg://modam@127.0.0.1:5432/modam_chat")
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    groq_model: str = Field(default="openai/gpt-oss-120b", min_length=1, max_length=100)
    groq_timeout_seconds: float = Field(default=30, ge=1, le=120)
    groq_api_key: SecretStr = Field(default=SecretStr(""), validation_alias="GROQ_API_KEY")
    groq_max_tokens: int = Field(default=1200, ge=100, le=4000)
    max_model_calls: int = Field(default=4, ge=1, le=10)
    max_tool_calls: int = Field(default=4, ge=1, le=20)
    max_replans: int = Field(default=1, ge=0, le=3)
    max_evidence_chars: int = Field(default=20000, ge=100, le=50000)
    tool_timeout_seconds: float = Field(default=15, gt=0, le=120)
    run_timeout_seconds: float = Field(default=90, gt=0, le=300)
    config_version: str = "chat-v1"
    prompt_version: str = "orchestration-v2"
