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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
