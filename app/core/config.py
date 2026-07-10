"""Application configuration loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Runtime settings for the MeetMind AI backend."""

    PROJECT_NAME: str = Field(..., description="Public application name.")
    VERSION: str = Field(..., description="Application version.")
    DATABASE_URL: str = Field(..., description="SQLAlchemy database URL.")
    OPENAI_API_KEY: str | None = Field(default=None, description="OpenAI API key reserved for future modules.")
    OPENAI_TRANSCRIPTION_MODEL: str = Field(..., description="OpenAI speech-to-text model.")
    OPENAI_ANALYSIS_MODEL: str = Field(..., description="OpenAI model used for transcript analysis.")
    OPENAI_REQUEST_TIMEOUT_SECONDS: int = Field(..., description="OpenAI request timeout in seconds.")
    TRANSCRIPTION_MAX_RETRIES: int = Field(..., description="Maximum retry attempts for transient AI failures.")
    MAX_TOKENS_PER_CHUNK: int = Field(..., description="Estimated maximum transcript tokens per analysis chunk.")
    MAX_CHUNK_CHARACTERS: int = Field(..., description="Maximum transcript characters per analysis chunk.")
    CHUNK_OVERLAP_SIZE: int = Field(..., description="Number of trailing characters carried into the next chunk.")
    ENABLE_SMART_CHUNKING: bool = Field(..., description="Enable automatic long-transcript chunk analysis.")
    CHAT_MODEL: str = Field(..., description="OpenAI model used for meeting chat.")
    MAX_CHAT_HISTORY: int = Field(..., description="Maximum recent chat turns included in AI context.")
    MAX_CONTEXT_LENGTH: int = Field(..., description="Maximum context characters sent to the chat model.")
    CHAT_TEMPERATURE: float = Field(..., description="Temperature used for meeting chat responses.")
    PDF_INCLUDE_TRANSCRIPT: bool = Field(..., description="Include transcript text in meeting exports.")
    PDF_INCLUDE_CHAT_HISTORY: bool = Field(..., description="Include chat history in meeting exports.")
    EXPORT_BRANDING: str = Field(..., description="Branding text displayed in generated exports.")
    DEFAULT_EXPORT_FORMAT: str = Field(..., description="Default export format for clients.")
    FFMPEG_BINARY: str = Field(..., description="FFmpeg executable path or command name.")
    FFPROBE_BINARY: str = Field(..., description="FFprobe executable path or command name.")
    MAX_AUDIO_DURATION_SECONDS: int = Field(..., description="Maximum supported audio duration in seconds.")
    SECRET_KEY: str = Field(..., description="Application secret reserved for authentication.")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(..., description="JWT access token expiry in minutes.")
    ALGORITHM: str = Field(..., description="Token signing algorithm reserved for authentication.")
    UPLOAD_DIRECTORY: str = Field(..., description="Directory where uploaded files will be stored.")
    MAX_UPLOAD_SIZE: int = Field(..., description="Maximum allowed upload size in bytes.")
    LOG_LEVEL: str = Field(..., description="Application logging level.")
    ENVIRONMENT: str = Field(default="development", description="Current runtime environment.")
    ALLOWED_ORIGINS: str = Field(default="*", description="Comma-separated CORS allowed origins.")
    MAX_REQUEST_SIZE: int = Field(default=524_288_000, description="Maximum accepted request size in bytes.")
    REQUEST_TIMEOUT: int = Field(default=120, description="HTTP request timeout in seconds.")
    ENABLE_DEBUG: bool = Field(default=False, description="Enable FastAPI debug mode.")
    ENABLE_DOCS: bool = Field(default=True, description="Expose Swagger, ReDoc, and OpenAPI schema endpoints.")
    SECURITY_HEADERS: bool = Field(default=True, description="Attach baseline security headers to responses.")
    TRUSTED_HOSTS: str = Field(default="*", description="Comma-separated trusted host names.")
    RATE_LIMIT_ENABLED: bool = Field(default=False, description="Enable lightweight in-memory rate limiting.")
    RATE_LIMIT_REQUESTS: int = Field(default=120, description="Maximum requests per client per rate-limit window.")
    RATE_LIMIT_WINDOW_SECONDS: int = Field(default=60, description="Rate-limit window length in seconds.")

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()


settings = get_settings()
