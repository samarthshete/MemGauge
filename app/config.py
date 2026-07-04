"""Application settings."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    memgauge_backend: str = Field(default="mock", alias="MEMGAUGE_BACKEND")
    memgauge_api_token: str = Field(default="dev-token", alias="MEMGAUGE_API_TOKEN")
    postgres_dsn: str = Field(
        default="postgresql+asyncpg://memgauge:memgauge@postgres:5432/memgauge",
        alias="POSTGRES_DSN",
    )
    neo4j_uri: str = Field(default="bolt://neo4j:7687", alias="NEO4J_URI")
    neo4j_user: str = Field(default="neo4j", alias="NEO4J_USER")
    neo4j_password: str = Field(default="memgauge-dev", alias="NEO4J_PASSWORD")
    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")
    db_pool_size: int = Field(default=5, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=10, alias="DB_MAX_OVERFLOW")
    db_pool_timeout: int = Field(default=30, alias="DB_POOL_TIMEOUT")
    otel_exporter_otlp_endpoint: str = Field(default="", alias="OTEL_EXPORTER_OTLP_ENDPOINT")
    embedding_model: str = Field(default="BAAI/bge-small-en-v1.5", alias="EMBEDDING_MODEL")
    cors_allow_origins: str = Field(default="", alias="CORS_ALLOW_ORIGINS")
    rate_limit_per_min: int = Field(default=60, alias="RATE_LIMIT_PER_MIN")

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]

    @property
    def asyncpg_dsn(self) -> str:
        return self.postgres_dsn.replace("postgresql+asyncpg://", "postgresql://", 1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
