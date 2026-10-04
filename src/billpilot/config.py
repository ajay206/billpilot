"""Runtime settings. Secrets and persona keys come from the environment, never from code."""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_database_url(url: str) -> str:
    """Accept a Neon-style URL and the SQLAlchemy psycopg URL.

    Hosted Postgres consoles hand out postgresql:// or postgres://. The engine
    in this process is psycopg 3, which wants the postgresql+psycopg scheme.
    Query parameters such as sslmode are left as they are.
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://billpilot:billpilot@localhost:5432/billpilot"

    @field_validator("database_url", mode="before")
    @classmethod
    def _database_driver(cls, value: str) -> str:
        return normalize_database_url(value)

    api_key_customer: str = "dev-customer-key"
    api_key_csr: str = "dev-csr-key"
    api_key_ops: str = "dev-ops-key"
    customer_number: str = "CUST-000001"
    csr_code: str = "CSR-A"

    # Local default only. Render generates a value. See docs/decisions/0024.
    session_secret: str = "dev-session-secret"
    session_ttl_seconds: int = 8 * 60 * 60
    login_failure_limit: int = 8
    login_failure_window_seconds: int = 15 * 60

    @field_validator("session_secret")
    @classmethod
    def _session_secret_length(cls, value: str) -> str:
        if len(value) < 16:
            raise ValueError("SESSION_SECRET must be at least 16 characters.")
        return value

    seed: int = 42
    customer_count: int = 500
    months: int = 6
    ground_truth_path: str = "data/ground_truth.json"
    anomaly_counts: str = ""

    log_level: str = "INFO"
    rate_limit_customer_per_minute: int = 120
    rate_limit_csr_per_minute: int = 300
    rate_limit_ops_per_minute: int = 600

    # Chat model. "fake" is the scripted model used by tests and CI.
    # "api" calls an OpenAI-compatible /chat/completions endpoint.
    llm_backend: str = "fake"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_api_key: str = ""
    llm_timeout_seconds: float = 60.0
    # Optional JSON object keyed by model name. See billpilot.agent.cost.
    llm_price_table: str = ""
    llm_prompt_price_per_million: str = "0.15"
    llm_completion_price_per_million: str = "0.60"

    # "hash" is the default CPU embedder. "api" calls /embeddings. "fake" is for tests.
    embedding_backend: str = "hash"
    embedding_model: str = "text-embedding-3-small"

    # Where the CLI sends tool calls. The API process calls itself in-process instead.
    bss_base_url: str = "http://127.0.0.1:8000"

    agent_max_tool_calls: int = 12
    agent_max_tokens: int = 16000
    agent_tool_result_chars: int = 6000

    # Tracing is on only when all three are non-empty. See agent/tracing.py.
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = ""

    # "postgres" is the free-tier default (Render has no broker). Compose sets "redpanda".
    event_backend: str = "postgres"
    redpanda_bootstrap: str = "localhost:19092"
    event_consumer_enabled: bool = True
    event_poll_seconds: float = 2.0
    event_max_retries: int = 3
    stuck_bill_run_seconds: int = 900
    # 0 disables the in-process report job. Render uses a long interval so a free instance stays quiet.
    report_schedule_seconds: int = 21600

    @field_validator("event_backend", mode="before")
    @classmethod
    def _event_backend(cls, value: str) -> str:
        normalized = str(value).strip().lower()
        if normalized not in {"postgres", "redpanda"}:
            raise ValueError("EVENT_BACKEND must be postgres or redpanda.")
        return normalized


@lru_cache
def get_settings() -> Settings:
    return Settings()
