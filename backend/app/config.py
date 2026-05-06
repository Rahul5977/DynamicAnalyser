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

    AST_INDEX_MAX_FILES: int = 500
    AST_INDEX_MAX_FILE_SIZE_KB: int = 500
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

    # Static Analysis
    STATIC_ANALYSIS_TEMP_DIR: str = "./temp/static_analysis"
    STATIC_ANALYSIS_MAX_FILES: int = 300
    STATIC_ANALYSIS_COUNCIL_MODEL: str = "claude-sonnet-4-6"
    STATIC_ANALYSIS_MAX_CHUNK_LINES: int = 100
    STATIC_COUNCIL_TEMPERATURE: float = 0.3
    STATIC_MAX_REINVESTIGATIONS: int = 1

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
