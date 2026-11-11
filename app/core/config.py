from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Default is a free local model, so a missing .env can never trigger a paid call.
    llm_provider: Literal["ollama", "groq", "openai", "anthropic"] = "ollama"
    llm_model: str = ""            # applies to ANY provider; prefer the provider-specific variables below
    groq_model: str = ""
    anthropic_model: str = ""
    ollama_model: str = ""
    openai_model: str = ""
    anthropic_api_key: str = ""
    groq_api_key: str = ""
    openai_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434/v1"

    llm_cache: bool = True
    cache_dir: str = "./.cache/llm"
    data_dir: str = "./data"

    use_mcp: bool = True
    mcp_timeout: float = Field(30, gt=0)   # seconds before falling back to calling the analyzers directly
    node_binary: str = "node"
    # A typo here used to fall back to unsandboxed execution silently; now it is rejected at start-up.
    sandbox_mode: Literal["subprocess", "docker"] = "subprocess"
    sandbox_timeout: int = Field(30, gt=0)    # whole test run
    per_test_timeout: int = Field(5, gt=0)    # each individual test
    sandbox_image: str = "code-review-sandbox"
    max_test_attempts: int = Field(2, ge=1, le=5)

    chroma_dir: str = "./.chroma"
    knowledge_dir: str = "./knowledge"
    rag_top_k: int = Field(4, ge=1)
    max_code_chars: int = Field(20000, gt=0)

    @field_validator("llm_provider", "sandbox_mode", mode="before")
    @classmethod
    def _normalise(cls, value):
        return value.strip().lower() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _timeouts_make_sense(self):
        if self.per_test_timeout >= self.sandbox_timeout:
            raise ValueError("PER_TEST_TIMEOUT must be smaller than SANDBOX_TIMEOUT")
        return self


settings = Settings()
