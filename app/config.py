from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # --- Environment ---
    environment: str = "development"  # "development" or "production"

    # --- Model & Pipeline ---
    model_path: str = "model_weights/best.pt"
    processing_mode: str = "auto"  # "auto", "cpu", "gpu"
    batch_size: int = 8
    min_segment_duration: int = 5
    crf_value: int = 16
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    ffmpeg_preset: str = "veryslow"
    ffmpeg_threads: int = 4

    # --- Storage ---
    upload_dir: str = "storage/uploads"
    output_dir: str = "storage/outputs"

    # --- Upload & Validation ---
    max_upload_size_mb: int = 2048
    allowed_extensions: str = ".mp4,.avi,.mkv,.mov"

    # --- Job Management ---
    job_ttl_hours: int = 24
    max_concurrent_jobs: int = 3
    cleanup_interval_minutes: int = 30

    # --- Logging ---
    log_level: str = "INFO"

    # --- Server ---
    cors_origins: str = "*"
    api_v1_prefix: str = "/api/v1"
    uvicorn_host: str = "0.0.0.0"
    uvicorn_port: int = 8000

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def allowed_extensions_list(self) -> list[str]:
        return [ext.strip() for ext in self.allowed_extensions.split(",")]

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",")]


settings = Settings()
