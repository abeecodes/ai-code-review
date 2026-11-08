from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Default is a free local model, so a missing .env can never trigger a paid call.
    llm_provider: str = "ollama"
    llm_model: str = ""
    anthropic_api_key: str = ""
    groq_api_key: str = ""
    openai_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434/v1"

    llm_cache: bool = True
    cache_dir: str = "./.cache/llm"
    data_dir: str = "./data"

    use_mcp: bool = True
    node_binary: str = "node"
    sandbox_mode: str = "subprocess"  # subprocess | docker
    sandbox_timeout: int = 30         # whole test run
    per_test_timeout: int = 5         # each individual test
    sandbox_image: str = "code-review-sandbox"
    max_test_attempts: int = 2

    chroma_dir: str = "./.chroma"
    knowledge_dir: str = "./knowledge"
    rag_top_k: int = 4
    max_code_chars: int = 20000


settings = Settings()
