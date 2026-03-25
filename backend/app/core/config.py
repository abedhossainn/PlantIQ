"""
Configuration management for PlantIQ Backend.

Loads settings from environment variables with sensible defaults.
"""
import os
from pathlib import Path
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AliasChoices, Field


REPO_ROOT = Path(__file__).resolve().parents[3]
ROOT_ENV_FILE = REPO_ROOT / ".env"
DEFAULT_PIPELINE_PYTHON = str(REPO_ROOT / ".venv" / "bin" / "python")
DEFAULT_PIPELINE_SCRIPT = str(REPO_ROOT / "pipeline" / "src" / "cli" / "hitl_pipeline.py")


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Application
    APP_NAME: str = "PlantIQ Backend API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = Field(default=False, validation_alias="DEBUG")
    
    # API
    API_V1_PREFIX: str = "/api/v1"
    
    # CORS
    CORS_ORIGINS: List[str] = Field(
        default=["http://localhost:3000", "http://localhost:3001"],
        validation_alias="CORS_ORIGINS"
    )
    
    # Database
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://plantig_authenticator:plantig@localhost:5432/plantig",
        validation_alias="DATABASE_URL"
    )
    
    # JWT
    JWT_ALGORITHM: str = "RS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_TOKEN_EXPIRE_HOURS: int = 8
    JWT_ISSUER: str = "plantig-auth"
    JWT_AUDIENCE: str = "plantig"
    JWT_PRIVATE_KEY_PATH: str = "./secrets/jwt-private.pem"
    JWT_PUBLIC_KEY_PATH: str = "./secrets/jwt-public.pem"
    
    # LDAP
    LDAP_SERVER: str = Field(default="ldap://localhost:389", validation_alias="LDAP_SERVER")
    LDAP_BASE_DN: str = Field(default="dc=example,dc=com", validation_alias="LDAP_BASE_DN")
    LDAP_MOCK: bool = Field(default=True, validation_alias="LDAP_MOCK")
    
    # Pipeline
    PIPELINE_WORK_DIR: str = Field(
        default="./data/artifacts/hitl_workspace",
        validation_alias="PIPELINE_WORK_DIR"
    )
    PIPELINE_PYTHON_PATH: str = Field(
        default=DEFAULT_PIPELINE_PYTHON,
        validation_alias="PIPELINE_PYTHON_PATH"
    )
    PIPELINE_SCRIPT_PATH: str = Field(
        default=DEFAULT_PIPELINE_SCRIPT,
        validation_alias="PIPELINE_SCRIPT_PATH"
    )
    PIPELINE_TIMEOUT_SECONDS: int = Field(
        default=7200,  # 2 hours
        validation_alias="PIPELINE_TIMEOUT_SECONDS"
    )
    
    # File Storage
    UPLOAD_DIR: str = Field(default="./data/raw", validation_alias="UPLOAD_DIR")
    ARTIFACTS_DIR: str = Field(default="./data/artifacts", validation_alias="ARTIFACTS_DIR")
    MAX_UPLOAD_SIZE_MB: int = Field(default=100, validation_alias="MAX_UPLOAD_SIZE_MB")
    ALLOWED_EXTENSIONS: List[str] = Field(
        default=[".pdf"],
        validation_alias="ALLOWED_EXTENSIONS"
    )
    
    # Qdrant Vector Database
    QDRANT_HOST: str = Field(default="localhost", validation_alias="QDRANT_HOST")
    QDRANT_PORT: int = Field(default=6333, validation_alias="QDRANT_PORT")
    QDRANT_COLLECTION: str = Field(default="plantig_documents", validation_alias="QDRANT_COLLECTION")
    QDRANT_TIMEOUT: int = Field(default=30, validation_alias="QDRANT_TIMEOUT")
    
    # vLLM Server
    VLLM_HOST: str = Field(default="localhost", validation_alias="VLLM_HOST")
    VLLM_PORT: int = Field(default=8001, validation_alias="VLLM_PORT")
    TEXT_MODEL_ID: str = Field(
        default="Qwen/Qwen3-4B-Instruct",
        validation_alias=AliasChoices("TEXT_MODEL_ID", "VLLM_MODEL", "VLLM_MODEL_NAME")
    )
    VISION_MODEL_ID: str = Field(
        default="Qwen/Qwen3-VL-4B-Instruct",
        validation_alias=AliasChoices("VISION_MODEL_ID", "VLM_MODEL", "VLM_MODEL_NAME")
    )
    VLLM_TIMEOUT: int = Field(default=60, validation_alias="VLLM_TIMEOUT")
    VLLM_MAX_TOKENS: int = Field(default=2048, validation_alias="VLLM_MAX_TOKENS")
    VLLM_TEMPERATURE: float = Field(default=0.7, validation_alias="VLLM_TEMPERATURE")
    VLLM_TOP_P: float = Field(default=0.9, validation_alias="VLLM_TOP_P")
    
    # Embedding Model (for Qdrant queries)
    EMBEDDING_MODEL: str = Field(
        default="BAAI/bge-large-en-v1.5",
        validation_alias="EMBEDDING_MODEL"
    )
    EMBEDDING_DIM: int = Field(default=1024, validation_alias="EMBEDDING_DIM")
    
    # RAG Configuration
    RAG_TOP_K: int = Field(default=5, validation_alias="RAG_TOP_K")
    RAG_SCORE_THRESHOLD: float = Field(default=0.7, validation_alias="RAG_SCORE_THRESHOLD")
    RAG_MAX_CONTEXT_LENGTH: int = Field(default=8000, validation_alias="RAG_MAX_CONTEXT_LENGTH")
    
    # WebSocket
    WS_HEARTBEAT_INTERVAL: int = Field(default=30, validation_alias="WS_HEARTBEAT_INTERVAL")
    WS_MESSAGE_QUEUE_SIZE: int = Field(default=100, validation_alias="WS_MESSAGE_QUEUE_SIZE")
    
    model_config = SettingsConfigDict(
        env_file=ROOT_ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @property
    def VLLM_MODEL(self) -> str:
        """Backward-compatible alias for the configured text model identifier."""
        return self.TEXT_MODEL_ID


# Global settings instance
settings = Settings()


def get_settings() -> Settings:
    """Get application settings."""
    return settings


def get_upload_path(filename: str) -> Path:
    """Get full path for uploaded file."""
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir / filename


def get_artifacts_path(document_id: str, artifact_type: str) -> Path:
    """Get path for document artifacts stored by the HITL pipeline.

    Search order:
    1. PIPELINE_WORK_DIR/{document_id}/ — UUID-named subdirectory (new uploads)
    2. PIPELINE_WORK_DIR/ root — title-named flat artifacts (pipeline run offline)
    3. ARTIFACTS_DIR/{document_id}/ — legacy flat path
    """
    import glob as _glob

    # Map API artifact-type name → glob suffix pattern
    _SUFFIX_MAP: dict[str, str] = {
        "validation":   "*_validation.json",
        "manifest":     "*_manifest.json",
        "qa_report":    "*_qa_pre_review.json",
        "table_figure": "*_tables_figures.json",
        "review":       "*_review",
        "audit":        "*_audit.txt",
    }

    pattern = _SUFFIX_MAP.get(artifact_type, f"*_{artifact_type}*")

    # 1. UUID-named subdirectory
    work_dir = Path(settings.PIPELINE_WORK_DIR) / document_id
    matches = _glob.glob(str(work_dir / pattern))
    if matches:
        return Path(matches[0])

    # 2. Root of PIPELINE_WORK_DIR (artifacts named by document title, no UUID subdir)
    root_dir = Path(settings.PIPELINE_WORK_DIR)
    root_matches = _glob.glob(str(root_dir / pattern))
    if root_matches:
        return Path(sorted(root_matches)[0])

    # 3. Legacy flat path (pre-pipeline documents)
    legacy_dir = Path(settings.ARTIFACTS_DIR) / document_id
    legacy_dir.mkdir(parents=True, exist_ok=True)
    return legacy_dir / f"{artifact_type}.json"
