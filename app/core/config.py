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

    # --- Database ---
    database_url: str = "postgresql+asyncpg://postgres:Pastibisa123@localhost:5432/anotasi_db"
    database_echo: bool = False  # SQLAlchemy SQL logging (enable in dev)

    # --- Server ---
    cors_origins: str = "*"
    use_cors: bool = True  # Toggle CORS middleware on/off
    api_v1_prefix: str = "/api/v1"
    uvicorn_host: str = "0.0.0.0"
    uvicorn_port: int = 8000

    # --- JWT Authentication ---
    jwt_secret_key: str = ""  # MUST be set via environment variable
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 1440  # 24 hours
    jwt_refresh_token_expire_days: int = 7  # 7 days

    # --- Password Hashing ---
    bcrypt_rounds: int = 12  # bcrypt salt rounds (12+ recommended)

    # --- Rate Limiting ---
    rate_limit_login_attempts: int = 5  # Max failed attempts
    rate_limit_window_seconds: int = 900  # 15 minutes

    # --- Email Configuration ---
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    from_email: str = "noreply@anotasi.lbi.ac.id"

    # --- ASR Configuration ---
    # Tuned to match asr_code.ipynb settings exactly
    whisper_model_size: str = "large-v3"  # tiny, base, small, medium, large-v3
    whisper_compute_type: str = "float16"  # int8, float16, int8_float16
    whisper_beam_size: int = 5
    whisper_language: str = "id"  # Indonesian
    model_cache_dir: str = "model_weights"
    force_cpu: bool = False  # Set True to disable GPU even if available

    # --- MinIO / S3 Storage ---
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket_name: str = "anotasi-videos"
    minio_secure: bool = False  # Set True for HTTPS
    minio_region: str = "us-east-1"
    minio_presigned_url_expiry: int = 3600  # 1 hour (NFR10)

    @property
    def minio_endpoint_url(self) -> str:
        """Return MinIO endpoint with protocol."""
        protocol = "https" if self.minio_secure else "http"
        return f"{protocol}://{self.minio_endpoint}"

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

    @property
    def cors_enabled(self) -> bool:
        """Return whether CORS middleware should be enabled."""
        return self.use_cors


settings = Settings()
