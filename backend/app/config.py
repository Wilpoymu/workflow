from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Workflow"
    app_version: str = "0.1.0"
    debug: bool = True

    host: str = "127.0.0.1"
    port: int = 8000

    projects_base_dir: str = ""

    bridge_host: str = "127.0.0.1"
    bridge_ws_port: int = 8766

    whisper_model_size: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"

    job_store_path: str = "jobs.sqlite"

    # AI Providers for prompt generation
    openrouter_api_key: str = ""
    openrouter_model: str = "meta-llama/llama-3.3-70b-instruct:free"
    openrouter_fallback_models: str = "openai/gpt-oss-20b:free,google/gemma-4-31b-it:free,nvidia/nemotron-3-super-120b-a12b:free"

    google_ai_api_key: str = ""
    google_model: str = "gemini-2.0-flash"

    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"
    groq_batch_size: int = 8

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"

    prompt_provider_order: str = "openrouter,google,ollama"
    prompt_inter_fragment_delay_ms: int = 4200
    prompt_batch_size: int = 5

    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8000",
        "https://labs.google.com",
        "https://labs.google",
    ]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
