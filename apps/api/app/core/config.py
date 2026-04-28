"""
Configuration management for PlantIQ Backend.

Loads settings from environment variables with sensible defaults.
"""
import os
import sys
from pathlib import Path
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AliasChoices, Field


REPO_ROOT = Path(os.getenv("PLANTIQ_REPO_ROOT", Path(__file__).resolve().parents[3]))
ROOT_ENV_FILE = REPO_ROOT / ".env"
DEFAULT_PIPELINE_PYTHON = str(REPO_ROOT / ".venv" / "bin" / "python")
if not Path(DEFAULT_PIPELINE_PYTHON).exists():
    DEFAULT_PIPELINE_PYTHON = sys.executable
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
    JWT_PRIVATE_KEY_PATH: str = str(REPO_ROOT / "backend" / "secrets" / "jwt-private.pem")
    JWT_PUBLIC_KEY_PATH: str = str(REPO_ROOT / "backend" / "secrets" / "jwt-public.pem")
    
    # LDAP
    # LDAP_SERVER and LDAP_SERVER_URL are accepted interchangeably.
    LDAP_SERVER: str = Field(
        default="ldap://localhost:389",
        validation_alias=AliasChoices("LDAP_SERVER", "LDAP_SERVER_URL"),
    )
    LDAP_BASE_DN: str = Field(default="dc=example,dc=com", validation_alias="LDAP_BASE_DN")
    # LDAP_MOCK and USE_MOCK_LDAP are accepted interchangeably.
    LDAP_MOCK: bool = Field(
        default=True,
        validation_alias=AliasChoices("LDAP_MOCK", "USE_MOCK_LDAP"),
    )
    # Bind credentials for LDAP service account (never log).
    LDAP_BIND_DN: str = Field(default="", validation_alias="LDAP_BIND_DN")
    LDAP_BIND_PASSWORD: str = Field(default="", validation_alias="LDAP_BIND_PASSWORD")
    LDAP_USER_SEARCH_BASE: str = Field(default="", validation_alias="LDAP_USER_SEARCH_BASE")
    LDAP_PORT: int = Field(default=389, validation_alias="LDAP_PORT")
    LDAP_USE_SSL: bool = Field(default=False, validation_alias="LDAP_USE_SSL")
    LDAP_START_TLS: bool = Field(default=False, validation_alias="LDAP_START_TLS")
    LDAP_VERIFY_CERT_MODE: str = Field(default="required", validation_alias="LDAP_VERIFY_CERT_MODE")
    LDAP_SEARCH_FILTER_TEMPLATE: str = Field(
        default="(&(objectClass=person)(uid={username}))",
        validation_alias="LDAP_SEARCH_FILTER_TEMPLATE",
    )

    # Directory config encryption (required when storing directory bind credentials in DB)
    DIRECTORY_CONFIG_ENCRYPTION_KEY: str = Field(
        default="",
        validation_alias="DIRECTORY_CONFIG_ENCRYPTION_KEY",
    )
    
    # Pipeline
    PIPELINE_WORK_DIR: str = Field(
        default=str(REPO_ROOT / "data" / "artifacts" / "hitl_workspace"),
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
    PIPELINE_STALLED_GRACE_SECONDS: int = Field(
        default=300,
        validation_alias="PIPELINE_STALLED_GRACE_SECONDS",
    )
    
    # File Storage
    UPLOAD_DIR: str = Field(default=str(REPO_ROOT / "data" / "raw"), validation_alias="UPLOAD_DIR")
    ARTIFACTS_DIR: str = Field(default=str(REPO_ROOT / "data" / "artifacts"), validation_alias="ARTIFACTS_DIR")
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
    
    # LLM Inference Server (OpenAI-compatible; supports vLLM, Ollama, etc.)
    LLM_HOST: str = Field(
        default="localhost",
        validation_alias=AliasChoices("LLM_HOST", "VLLM_HOST")
    )
    LLM_PORT: int = Field(
        default=11434,
        validation_alias=AliasChoices("LLM_PORT", "VLLM_PORT")
    )
    TEXT_MODEL_ID: str = Field(
        default="Qwen/Qwen3-4B-Instruct",
        validation_alias=AliasChoices("TEXT_MODEL_ID", "VLLM_MODEL", "VLLM_MODEL_NAME")
    )
    LLM_BACKEND: str = Field(
        default="openai-compatible",
        validation_alias=AliasChoices("LLM_BACKEND", "TEXT_INFERENCE_BACKEND")
    )
    LLM_UNLOAD_AFTER_REQUEST: bool = Field(default=False, validation_alias="LLM_UNLOAD_AFTER_REQUEST")
    LLM_DEMAND_HEARTBEAT_FILE: str = Field(
        default=str(REPO_ROOT / "data" / "artifacts" / "runtime" / "llm_last_used"),
        validation_alias="LLM_DEMAND_HEARTBEAT_FILE"
    )
    LLM_STARTUP_WAIT_SECONDS: int = Field(default=45, validation_alias="LLM_STARTUP_WAIT_SECONDS")
    LLM_RETRY_INTERVAL_SECONDS: float = Field(default=1.0, validation_alias="LLM_RETRY_INTERVAL_SECONDS")
    VLM_HOST: str = Field(default="localhost", validation_alias="VLM_HOST")
    VLM_PORT: int = Field(default=8000, validation_alias="VLM_PORT")
    VISION_MODEL_ID: str = Field(
        default="Qwen/Qwen3-VL-4B-Instruct",
        validation_alias=AliasChoices("VISION_MODEL_ID", "VLM_MODEL", "VLM_MODEL_NAME")
    )
    LLM_TIMEOUT: int = Field(
        default=60,
        validation_alias=AliasChoices("LLM_TIMEOUT", "VLLM_TIMEOUT")
    )
    LLM_MAX_TOKENS: int = Field(
        default=2048,
        validation_alias=AliasChoices("LLM_MAX_TOKENS", "VLLM_MAX_TOKENS")
    )
    LLM_TEMPERATURE: float = Field(
        default=0.7,
        validation_alias=AliasChoices("LLM_TEMPERATURE", "VLLM_TEMPERATURE")
    )
    LLM_TOP_P: float = Field(
        default=0.9,
        validation_alias=AliasChoices("LLM_TOP_P", "VLLM_TOP_P")
    )
    
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

    # Chat workspace and retrieval policy
    CHAT_INCLUDE_SHARED_DEFAULT: bool = Field(default=True, validation_alias="CHAT_INCLUDE_SHARED_DEFAULT")
    CHAT_ALLOW_WORKSPACE_FALLBACK_TO_SHARED: bool = Field(
        default=True,
        validation_alias="CHAT_ALLOW_WORKSPACE_FALLBACK_TO_SHARED",
    )
    CHAT_CANONICAL_WORKSPACES: str = Field(
        default=(
            "Power Block,Pre Treatment,Liquefaction,OSBL (Outside Battery Limits),"
            "Maintenance,Instrumentation,DCS (Distributed Control System),Electrical,Mechanical"
        ),
        validation_alias="CHAT_CANONICAL_WORKSPACES",
    )
    
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

    @property
    def VLLM_HOST(self) -> str:
        """Backward-compatible alias for legacy settings access."""
        return self.LLM_HOST

    @property
    def VLLM_PORT(self) -> int:
        """Backward-compatible alias for legacy settings access."""
        return self.LLM_PORT

    @property
    def VLLM_TIMEOUT(self) -> int:
        """Backward-compatible alias for legacy settings access."""
        return self.LLM_TIMEOUT

    @property
    def VLLM_MAX_TOKENS(self) -> int:
        """Backward-compatible alias for legacy settings access."""
        return self.LLM_MAX_TOKENS

    @property
    def VLLM_TEMPERATURE(self) -> float:
        """Backward-compatible alias for legacy settings access."""
        return self.LLM_TEMPERATURE

    @property
    def VLLM_TOP_P(self) -> float:
        """Backward-compatible alias for legacy settings access."""
        return self.LLM_TOP_P


# Global settings instance
settings = Settings()


def get_settings() -> Settings:
    """Get application settings."""
    return settings


def get_canonical_workspaces() -> list[str]:
    """Return configured canonical workspace names in declaration order."""
    raw_value = settings.CHAT_CANONICAL_WORKSPACES
    return [item.strip() for item in raw_value.split(",") if item and item.strip()]


def get_upload_path(filename: str) -> Path:
    """Get full path for uploaded file."""
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir / filename


def get_artifacts_path(
    document_id: str,
    artifact_type: str,
    *,
    allow_legacy_qa_fallback: bool = True,
) -> Path:
    """Get path for document artifacts stored by the HITL pipeline.

    Search order:
    1. PIPELINE_WORK_DIR/{document_id}/ — UUID-named subdirectory (new uploads)
    2. PIPELINE_WORK_DIR/ root — title-named flat artifacts (pipeline run offline)
    3. ARTIFACTS_DIR/{document_id}/ — legacy flat path
    """
    import glob as _glob

    # Map API artifact-type name → glob suffix pattern
    qa_report_patterns = ["*_qa_report.json"]
    if allow_legacy_qa_fallback:
        qa_report_patterns.append("*_qa_pre_review.json")

    _SUFFIX_MAP: dict[str, list[str]] = {
        "validation": ["*_validation.json"],
        "manifest": ["*_manifest.json"],
        "qa_report": qa_report_patterns,
        "table_figure": ["*_tables_figures.json"],
        "review": ["*_review"],
        "audit": ["*_audit.txt"],
        "optimization_prep": ["*_optimization_prep.json"],
        "optimized_output": ["*_rag_optimized.json", "*_rag_optimized.md"],
    }

    patterns = _SUFFIX_MAP.get(artifact_type, [f"*_{artifact_type}*"])

    def _find_first_match(search_root: Path) -> Path | None:
        # Try patterns in declaration order so earlier patterns take priority.
        # Critical for "qa_report": *_qa_report.json must win over the legacy
        # *_qa_pre_review.json when both are present in the same directory.
        for pattern in patterns:
            pattern_matches = sorted(_glob.glob(str(search_root / pattern)))
            if pattern_matches:
                return Path(pattern_matches[0])
        return None

    # 1. UUID-named subdirectory
    work_dir = Path(settings.PIPELINE_WORK_DIR) / document_id
    work_match = _find_first_match(work_dir)
    if work_match is not None:
        return work_match

    # 2. Root of PIPELINE_WORK_DIR (artifacts named by document title, no UUID subdir)
    root_dir = Path(settings.PIPELINE_WORK_DIR)
    root_match = _find_first_match(root_dir)
    if root_match is not None:
        return root_match

    # 3. Legacy flat path (pre-pipeline documents)
    legacy_dir = Path(settings.ARTIFACTS_DIR) / document_id
    legacy_dir.mkdir(parents=True, exist_ok=True)
    return legacy_dir / f"{artifact_type}.json"
