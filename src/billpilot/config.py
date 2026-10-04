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


@lru_cache
def get_settings() -> Settings:
    return Settings()
