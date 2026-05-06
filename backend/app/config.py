from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    APP_NAME: str = "DynamicAnalyser"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False

    DATABASE_URL: str = "sqlite:///./dynamic_analyser.db"

    GITHUB_TOKEN: str = ""
    GITHUB_API_TIMEOUT: int = 30

    LOG_LEVEL: str = "INFO"

    SLOW_STEP_THRESHOLD_MS: int = 5000

    AST_INDEX_MAX_FILES: int = 5000
    AST_INDEX_MAX_FILE_SIZE_KB: int = 2048
    AST_INDEX_LOCAL_ROOT: str = ""
    FUZZY_MATCH_THRESHOLD: float = 0.85
    BOTTLENECK_DEFAULT_WINDOW: int = 50

    ANTHROPIC_API_KEY: str = ""
    LLM_MODEL: str = "claude-sonnet-4-6"
    LLM_MAX_OUTPUT_TOKENS: int = 3000
    LLM_CONTEXT_TOKEN_BUDGET: int = 12000
    ANALYSIS_TARGET_DURATION_MS: int = 15000
    ANALYSIS_BOTTLENECK_TOP_N: int = 3
    ANALYSIS_HISTORY_WINDOW: int = 20

    GITHUB_WEBHOOK_SECRET: str = ""
    DASHBOARD_URL: str = "http://localhost:5173"
    DEMO_MODE: bool = False

    APP_LOG_UPLOAD_DIR: str = "./uploads/app_logs"
    APP_LOG_MAX_SIZE_MB: int = 50

    STATIC_ANALYSIS_MAX_REPO_FILES: int = 800
    STATIC_ANALYSIS_MAX_FILES_PER_DOMAIN: int = 45
    STATIC_ANALYSIS_MAX_CHARS_PER_FILE: int = 14_000
    STATIC_ANALYSIS_LLM_MAX_TOKENS: int = 8192

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
