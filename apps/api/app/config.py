from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_data_dir() -> Path:
    current_file = Path(__file__).resolve()
    for parent in current_file.parents:
        if (parent / "docs").exists() and (parent / "apps").exists():
            return parent / "data"
    return current_file.parents[1] / "data"


class Settings(BaseSettings):
    app_name: str = "Urbanization Tracker API"
    database_url: str = "postgresql+psycopg://urbanization:urbanization@localhost:5432/urbanization_tracker"
    redis_url: str = "redis://localhost:6379/0"
    ingestion_data_dir: Path = Field(
        default_factory=_default_data_dir,
        description="Directory for raw, processed, and health ingestion artifacts.",
    )
    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        description="Comma-separated list of allowed browser origins.",
    )

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
