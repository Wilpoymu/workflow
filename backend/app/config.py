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

    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8000",
        "https://labs.google.com",
        "https://labs.google",
    ]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
