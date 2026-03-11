# JBI Detection & Segmentation API

FastAPI backend for detecting and segmenting JBI (Juru Bahasa Isyarat) overlays in news broadcast videos using a custom-trained YOLOv8 model.

## Prerequisites

- Python 3.11+
- FFmpeg installed and available in PATH
- YOLO model weights (`best.pt`) placed in `model_weights/`

**For GPU acceleration (optional):**

- NVIDIA GPU with CUDA 12.6 compatible drivers
- NVIDIA Container Toolkit (for Docker GPU mode)

## Quick Start (Local)

### 1. Create virtual environment

```bash
cd cv_backend
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux/macOS
source .venv/bin/activate
```

### 2. Install dependencies

**CPU only:**

```bash
pip install -r requirements.txt
```

**GPU (CUDA 12.6):**

```bash
pip install -r requirements-torch-gpu.txt
pip install -r requirements.txt
```

### 3. Add model weights

Place your trained YOLOv8 model file at:

```
cv_backend/model_weights/best.pt
```

### 4. Configure environment (optional)

```bash
copy .env.example .env
```

All settings have sensible defaults. The `.env` file is optional for development.

### 5. Run the server

```bash
python run.py
```

The server starts at `http://localhost:8000` with auto-reload enabled in development mode.

- Swagger UI: <http://localhost:8000/docs>
- API root: <http://localhost:8000/>

## Quick Start (Docker)

### CPU mode

```bash
copy .env.example .env
docker compose --profile cpu up --build
```

### GPU mode

Requires NVIDIA Container Toolkit installed on the host.

```bash
copy .env.production .env
docker compose --profile gpu up --build
```

## API Endpoints

| Method   | Path                                          | Description                     |
| -------- | --------------------------------------------- | ------------------------------- |
| `POST`   | `/api/v1/jobs`                                | Upload video or provide URL     |
| `GET`    | `/api/v1/jobs/{job_id}`                       | Poll job status and progress    |
| `DELETE` | `/api/v1/jobs/{job_id}`                       | Cancel a job                    |
| `GET`    | `/api/v1/jobs/{job_id}/results`               | Get detection results (JSON)    |
| `GET`    | `/api/v1/jobs/{job_id}/segments/{i}/download` | Download cropped segment (MP4)  |
| `GET`    | `/api/v1/health`                              | Health check                    |

## Usage Examples

### Upload a video file

```bash
curl -X POST http://localhost:8000/api/v1/jobs \
  -F "file=@video.mp4"
```

### Submit a video URL

```bash
curl -X POST http://localhost:8000/api/v1/jobs \
  -F "url=https://example.com/video.mp4"
```

### Poll job status

```bash
curl http://localhost:8000/api/v1/jobs/{job_id}
```

Response while processing:

```json
{
  "job_id": "...",
  "status": "processing",
  "progress": {
    "phase": "detection",
    "current": 340,
    "total": 3400,
    "percent": 10.0
  }
}
```

### Get results (after completion)

```bash
curl http://localhost:8000/api/v1/jobs/{job_id}/results
```

### Download a segment

```bash
curl -o segment_000000.mp4 \
  http://localhost:8000/api/v1/jobs/{job_id}/segments/0/download
```

### Cancel a job

```bash
curl -X DELETE http://localhost:8000/api/v1/jobs/{job_id}
```

## Configuration

All settings are configurable via environment variables or a `.env` file. Key settings:

| Variable               | Default         | Description                                  |
| ---------------------- | --------------- | -------------------------------------------- |
| `ENVIRONMENT`          | `development`   | `development` (reload) or `production`       |
| `MODEL_PATH`           | `model_weights/best.pt` | Path to YOLO model weights           |
| `PROCESSING_MODE`      | `auto`          | `auto`, `cpu`, or `gpu`                      |
| `BATCH_SIZE`           | `8`             | Frames per YOLO batch                        |
| `MIN_SEGMENT_DURATION` | `5`             | Minimum segment length in seconds            |
| `MAX_UPLOAD_SIZE_MB`   | `2048`          | Maximum upload size                          |
| `JOB_TTL_HOURS`        | `24`            | Auto-cleanup after this many hours           |
| `LOG_LEVEL`            | `INFO`          | Logging level                                |
| `UVICORN_PORT`         | `8000`          | Server port                                  |
| `CORS_ORIGINS`         | `*`             | Allowed CORS origins (comma-separated)       |
| `FFMPEG_PRESET`        | `veryslow`      | FFmpeg encoding preset (use `medium` in prod)|

See [.env.example](.env.example) for the full list.

## Project Structure

```
cv_backend/
├── app/
│   ├── main.py                  # FastAPI app with lifespan, middleware, routers
│   ├── config.py                # Pydantic Settings (env-driven)
│   ├── exception_handlers.py    # Global error handlers (400, 422, 500)
│   ├── logging_config.py        # Structured JSON logging + ContextVars
│   ├── middleware.py             # Request logging middleware (timing, request_id)
│   ├── models/
│   │   ├── job.py               # Job dataclass, JobStatus enum, state machine
│   │   ├── job_store.py         # Thread-safe in-memory job store
│   │   └── schemas.py           # Pydantic response models
│   ├── routers/
│   │   ├── health.py            # GET /health (model, GPU, disk checks)
│   │   └── jobs.py              # All job endpoints (create, status, cancel, results, download)
│   ├── services/
│   │   ├── detector.py          # YOLOv8 detection service
│   │   ├── segmenter.py         # Contiguous segment identification
│   │   ├── cropper.py           # Video cropping with MoviePy
│   │   ├── pipeline.py          # Orchestrator: detect → segment → crop
│   │   ├── validator.py         # Upload validation (extension, size, OpenCV probe)
│   │   ├── downloader.py        # URL video download (streamed)
│   │   ├── cleanup.py           # TTL-based job/file cleanup
│   │   └── scheduler.py         # Periodic cleanup scheduler
│   └── workers/
│       └── tasks.py             # Background task with cooperative cancellation
├── model_weights/               # Place best.pt here
├── storage/
│   ├── uploads/                 # Uploaded/downloaded videos
│   └── outputs/                 # Cropped segments per job
├── tests/
├── run.py                       # Entry point (dev/prod aware)
├── requirements.txt             # Python dependencies (CPU)
├── requirements-torch-gpu.txt   # PyTorch CUDA 12.6
├── Dockerfile                   # CPU image
├── Dockerfile.gpu               # GPU image (NVIDIA CUDA)
├── docker-compose.yml           # Profiles: cpu, gpu
├── .env.example                 # All env vars with defaults
├── .env.production              # Production recommended values
├── .dockerignore
└── .gitignore
```

## Processing Pipeline

```
Upload/URL → Validate → Save to disk → Background task:
  1. Detection  — YOLO inference at 1 fps, outputs per-second boolean map
  2. Segmentation — Finds contiguous detected ranges, filters by min duration
  3. Cropping  — Exports each segment as MP4 (bbox-cropped, with audio)
```

## Production Deployment

For production, use the `.env.production` template:

```bash
copy .env.production .env
```

Key production differences:

- `ENVIRONMENT=production` — disables auto-reload, uses structured JSON logging only
- `FFMPEG_PRESET=medium` — 5-10x faster encoding vs `veryslow`
- `CORS_ORIGINS` — restrict to your frontend domain

**Important:** The MVP uses 1 uvicorn worker because the in-memory job store is per-process. Multiple workers would break job status polling.
