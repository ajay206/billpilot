"""Runtime settings. Secrets and persona keys come from the environment, never from code."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://billpilot:billpilot@localhost:5432/billpilot"

    api_key_customer: str = "dev-customer-key"
    api_key_csr: str = "dev-csr-key"
    api_key_ops: str = "dev-ops-key"
    customer_number: str = "CUST-000001"
    csr_code: str = "CSR-A"

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

    agent_max_tool_calls: int = 8
    agent_max_tokens: int = 16000
    agent_tool_result_chars: int = 6000

    langfuse_enabled: bool = False
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"


@lru_cache
def get_settings() -> Settings:
    return Settings()
