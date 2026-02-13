# PRD: JBI Detection & Segmentation — FastAPI Backend

| Field          | Value                                      |
| -------------- | ------------------------------------------ |
| **Product**    | JBI Detection & Segmentation API           |
| **Version**    | 1.0                                        |
| **Author**     | PM / Engineering                           |
| **Status**     | Draft                                      |
| **Created**    | 2026-02-11                                 |
| **Stack**      | FastAPI, Ultralytics YOLOv8, OpenCV, MoviePy, Celery/Redis |

---

## 1. Overview

### 1.1 Background

The team has built a Jupyter notebook (`VideoDetector3.ipynb`) that uses a custom-trained YOLOv8 model (`best.pt`) to:

1. Scan a news broadcast video frame-by-frame (1 fps sampling).
2. Detect the presence of a target object (e.g. news lower-third / JBI overlay) in each second.
3. Identify contiguous segments (>= 5 s) where the object appears.
4. Crop each segment to the detected bounding box and export it as a standalone MP4 (with audio).

This works end-to-end but runs only inside a notebook. The goal is to wrap this CV pipeline into a **production-grade FastAPI backend** so it can be consumed by any frontend or external service via REST API.

### 1.2 Problem Statement

- The current workflow is manual: a user must edit hardcoded paths in a notebook cell and run all cells sequentially.
- There is no way for multiple users or external systems to submit videos for processing.
- There is no progress feedback, job management, or error handling beyond `print()` statements.
- Output files are written to disk with no structured metadata or retrieval mechanism.

### 1.3 Goal

Deliver a FastAPI service that exposes the full detect-segment-crop pipeline as an async API with:

- Video upload / URL ingest
- Background job processing with progress tracking
- Structured JSON results (detection timeline, segments, download links)
- File download endpoints for cropped clips

---

## 2. Target Users

| Persona             | Description                                                                                  |
| -------------------- | -------------------------------------------------------------------------------------------- |
| **Frontend Client**  | A web or mobile app that lets users upload news videos and retrieve cropped JBI segments.     |
| **Researcher**       | A data analyst who batch-processes datasets of news broadcasts via API scripts.               |
| **Internal Service** | Another microservice in a larger pipeline (e.g. transcription, archival) that calls this API. |

---

## 3. Functional Requirements

### FR-1 — Video Ingestion
- **FR-1.1** Upload a video file via `multipart/form-data` (supported formats: MP4, AVI, MKV, MOV).
- **FR-1.2** Alternatively provide a publicly-accessible URL; the backend downloads the video.
- **FR-1.3** Validate file type / size (configurable max, default 2 GB).
- **FR-1.4** Return a `job_id` immediately upon accepted upload.

### FR-2 — Detection & Segmentation Processing
- **FR-2.1** Run YOLOv8 inference on each second of the video (batch processing, configurable batch size).
- **FR-2.2** Support CPU and GPU processing modes (auto-detect or configurable).
- **FR-2.3** Identify contiguous detection segments with configurable minimum duration (default 5 s).
- **FR-2.4** Crop detected segments using the first-frame bounding box and export as MP4 with audio.

### FR-3 — Job Management
- **FR-3.1** Return job status: `queued → processing → completed → failed`.
- **FR-3.2** Expose progress metadata: `current_second`, `total_seconds`, `percent_complete`.
- **FR-3.3** Support cancelling a queued or in-progress job.
- **FR-3.4** Retain job results for a configurable TTL (default 24 h), then auto-cleanup.
- **FR-3.5** List all jobs with optional status filtering, supporting pagination via `limit` and `offset` query parameters.

### FR-4 — Results & Downloads
- **FR-4.1** Return structured JSON with detection timeline (per-second boolean array).
- **FR-4.2** Return segment list with `start_time`, `end_time`, `duration`, `bbox`, and `download_url`.
- **FR-4.3** Serve cropped video files via a streaming download endpoint.
- **FR-4.4** Optionally return a detection summary text file (`object_detection_times.txt` equivalent).

### FR-5 — Configuration
- **FR-5.1** `batch_size`, `min_segment_duration`, `crf_value`, and `processing_mode` are backend-only settings managed via `.env` / server config. They are not exposed to the client.
- **FR-5.2** Support swapping YOLO model weights via config (path to `.pt` file).

---

## 4. Non-Functional Requirements

| ID      | Requirement                                                                                 |
| ------- | ------------------------------------------------------------------------------------------- |
| NFR-1   | **Async Processing** — Video processing must run in background workers, not block the API.  |
| NFR-2   | **Concurrency** — Support at least 3 concurrent jobs (bounded by GPU/CPU resource limits).  |
| NFR-3   | **Latency** — Upload endpoint responds in < 2 s. Status poll responds in < 200 ms.         |
| NFR-4   | **Storage** — Temporary files cleaned up after TTL. Configurable output directory.          |
| NFR-5   | **Error Handling** — Graceful error responses (4xx/5xx) with meaningful messages.           |
| NFR-6   | **Logging** — Structured JSON logging for all operations (ingestion, detection, export).    |
| NFR-7   | **Health Check** — `/health` endpoint returns model loaded status, GPU availability, disk space. |
| NFR-8   | **CORS** — Configurable CORS origins for frontend integration.                              |

---

## 5. System Architecture

```
┌──────────────────────────────────────────────────────────┐
│                      Client / Frontend                   │
└──────────────┬───────────────────────────┬───────────────┘
               │  POST /api/v1/jobs        │  GET /api/v1/jobs/{id}
               │  (upload video)           │  (poll status)
               ▼                           ▼
┌──────────────────────────────────────────────────────────┐
│                     FastAPI Application                   │
│                                                          │
│  ┌──────────┐  ┌──────────────┐  ┌────────────────────┐ │
│  │  Router   │  │  Job Manager │  │  File Server       │ │
│  │  (REST)   │  │  (state)     │  │  (downloads)       │ │
│  └──────────┘  └──────┬───────┘  └────────────────────┘ │
└─────────────────────────┼────────────────────────────────┘
                          │ enqueue
                          ▼
┌──────────────────────────────────────────────────────────┐
│              Background Task Worker                       │
│                                                          │
│  ┌──────────────────────────────────────────────┐        │
│  │  Detection Pipeline                          │        │
│  │  1. Load video (OpenCV)                      │        │
│  │  2. Batch YOLO inference (per-second frames) │        │
│  │  3. Segment extraction                       │        │
│  │  4. Crop & export (MoviePy + FFmpeg)         │        │
│  └──────────────────────────────────────────────┘        │
│                                                          │
│  ┌─────────────┐  ┌──────────┐                           │
│  │ YOLO Model  │  │ GPU/CPU  │                           │
│  │ (best.pt)   │  │ Device   │                           │
│  └─────────────┘  └──────────┘                           │
└──────────────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────┐
│                     Storage (Disk)                        │
│                                                          │
│   uploads/          outputs/{job_id}/                    │
│   ├── {job_id}.mp4  ├── segment_000000.mp4               │
│                     ├── segment_001234.mp4               │
│                     └── detection_times.txt              │
└──────────────────────────────────────────────────────────┘
```

---

## 6. API Contract (Draft)

### 6.1 Create Job — Upload Video

```
POST /api/v1/jobs
Content-Type: multipart/form-data

Form fields:
  file:                   <video file>          (required if no url)
  url:                    <string>              (required if no file)

Note: processing_mode, batch_size, min_segment_duration, and crf_value are
server-side configuration only (set via .env / backend config). They are NOT
exposed to the client.

Response 202:
{
  "job_id": "abc-123-def",
  "status": "queued",
  "created_at": "2026-02-11T10:00:00Z"
}
```

### 6.2 Get Job Status

```
GET /api/v1/jobs/{job_id}

Response 200:
{
  "job_id": "abc-123-def",
  "status": "processing",
  "progress": {
    "current_second": 340,
    "total_seconds": 3400,
    "percent": 10.0
  },
  "created_at": "2026-02-11T10:00:00Z",
  "updated_at": "2026-02-11T10:02:15Z"
}
```

### 6.3 Get Job Results

```
GET /api/v1/jobs/{job_id}/results

Response 200:
{
  "job_id": "abc-123-def",
  "status": "completed",
  "video_metadata": {
    "fps": 30.0,
    "total_frames": 102000,
    "duration_seconds": 3400.0
  },
  "detection_summary": {
    "total_seconds_scanned": 3400,
    "seconds_with_detection": 2800
  },
  "segments": [
    {
      "index": 0,
      "start_time": "0:02:52",
      "end_time": "0:03:25",
      "start_seconds": 172,
      "end_seconds": 205,
      "duration_seconds": 33,
      "bbox": { "x_min": 120, "y_min": 450, "width": 800, "height": 120 },
      "download_url": "/api/v1/jobs/abc-123-def/segments/0/download"
    }
  ]
}
```

### 6.4 Download Segment

```
GET /api/v1/jobs/{job_id}/segments/{index}/download

Response 200: video/mp4 stream
```

### 6.5 Cancel Job

```
DELETE /api/v1/jobs/{job_id}

Response 200:
{ "job_id": "abc-123-def", "status": "cancelled" }
```

### 6.6 List All Jobs

```
GET /api/v1/jobs?status=processing&limit=20&offset=0

Query parameters (all optional):
  status:   Filter by job status (queued, processing, completed, failed, cancelled)
  limit:    Maximum number of jobs to return (default 20, max 100)
  offset:   Number of jobs to skip for pagination (default 0)

Response 200:
{
  "jobs": [
    {
      "job_id": "abc-123-def",
      "status": "processing",
      "progress": {
        "phase": "detection",
        "current": 340,
        "total": 3400,
        "percent": 10.0
      },
      "error": null,
      "created_at": "2026-02-11T10:00:00Z",
      "updated_at": "2026-02-11T10:02:15Z"
    },
    {
      "job_id": "xyz-789-ghi",
      "status": "completed",
      "progress": null,
      "error": null,
      "created_at": "2026-02-11T09:00:00Z",
      "updated_at": "2026-02-11T09:30:00Z"
    }
  ],
  "total": 42,
  "limit": 20,
  "offset": 0
}
```

### 6.7 Health Check

```
GET /api/v1/health

Response 200:
{
  "status": "healthy",
  "model_loaded": true,
  "gpu_available": true,
  "gpu_name": "NVIDIA RTX 3060",
  "disk_free_gb": 42.5
}
```

---

## 7. Epics & Stories Breakdown

### Epic 1: Project Setup & Scaffolding
> *Establish the project structure, dependency management, and development environment.*

| Story | Description | Priority |
| ----- | ----------- | -------- |
| 1.1   | Initialize FastAPI project structure (`app/`, `routers/`, `services/`, `models/`, `workers/`, `config/`) | P0 |
| 1.2   | Create `requirements.txt` / `pyproject.toml` with all dependencies (fastapi, uvicorn, ultralytics, opencv, moviepy, celery, redis, python-multipart) | P0 |
| 1.3   | Set up configuration management (`.env` file, pydantic `Settings` class) for model path, storage dirs, max upload size, TTL, CORS origins | P0 |
| 1.4   | Add Dockerfile and `docker-compose.yml` (API + Redis + Worker) | P1 |
| 1.5   | Add `.gitignore` for uploads/, outputs/, `.env`, `__pycache__`, `.venv/` | P0 |

### Epic 2: Core CV Pipeline Refactor
> *Extract the notebook logic into clean, testable Python modules.*

| Story | Description | Priority |
| ----- | ----------- | -------- |
| 2.1   | Create `services/detector.py` — encapsulate YOLO model loading, batch inference, and per-second detection logic | P0 |
| 2.2   | Create `services/segmenter.py` — implement segment identification (contiguous detection windows >= min_duration) | P0 |
| 2.3   | Create `services/cropper.py` — implement bbox-based video cropping and MP4 export with audio | P0 |
| 2.4   | Create `services/pipeline.py` — orchestrate the full detect → segment → crop pipeline with progress callbacks | P0 |
| 2.5   | Add unit tests for detector, segmenter, cropper with mock video data | P1 |
| 2.6   | Validate output parity: ensure API pipeline produces identical results to the notebook | P0 |

### Epic 3: Video Ingestion & Validation
> *Handle video upload, URL download, and input validation.*

| Story | Description | Priority |
| ----- | ----------- | -------- |
| 3.1   | Implement `POST /api/v1/jobs` with multipart file upload, save to `uploads/{job_id}.ext` | P0 |
| 3.2   | Implement URL-based ingestion: download video from provided URL to `uploads/` | P1 |
| 3.3   | Add file validation: check MIME type, file extension, max file size | P0 |
| 3.4   | Add video validation: probe with OpenCV to ensure file is a valid, readable video | P0 |
| 3.5   | Return `job_id` (UUID) immediately after accepted upload | P0 |

### Epic 4: Job Management & Background Processing
> *Queue jobs, run them in background workers, and track state.*

| Story | Description | Priority |
| ----- | ----------- | -------- |
| 4.1   | Define job state model: `queued → processing → completed → failed → cancelled` | P0 |
| 4.2   | Implement in-memory job store (dict-based) for MVP; define interface for future DB swap | P0 |
| 4.3   | Integrate background task execution (FastAPI `BackgroundTasks` for MVP, Celery for production) | P0 |
| 4.4   | Wire pipeline progress callbacks to update job store (`current_second`, `total_seconds`, `percent`) | P0 |
| 4.5   | Implement `GET /api/v1/jobs/{job_id}` — return current status + progress | P0 |
| 4.6   | Implement `DELETE /api/v1/jobs/{job_id}` — cancel a queued/in-progress job | P1 |
| 4.7   | Implement job TTL: auto-delete job data and output files after configurable expiry | P2 |
| 4.8   | Implement `GET /api/v1/jobs` — list all jobs with optional status filter and pagination | P1 |
| 4.9   | Migrate in-memory job store to PostgreSQL with SQLAlchemy async + Alembic migrations | P1 |

### Epic 5: Results & File Serving
> *Structure and serve detection results and cropped video files.*

| Story | Description | Priority |
| ----- | ----------- | -------- |
| 5.1   | Implement `GET /api/v1/jobs/{job_id}/results` — return structured JSON with segments, bbox, and download links | P0 |
| 5.2   | Implement `GET /api/v1/jobs/{job_id}/segments/{index}/download` — stream cropped MP4 file | P0 |
| 5.3   | Add detection timeline endpoint or include per-second boolean array in results | P2 |
| 5.4   | Generate and serve `detection_times.txt` equivalent as downloadable file | P2 |

### Epic 6: API Hardening & Observability
> *Error handling, logging, health checks, and CORS.*

| Story | Description | Priority |
| ----- | ----------- | -------- |
| 6.1   | Add global exception handler with structured error responses (`{"error": ..., "detail": ...}`) | P0 |
| 6.2   | Add request validation error handler (Pydantic 422 → readable messages) | P0 |
| 6.3   | Implement `GET /api/v1/health` — model loaded, GPU status, disk space | P0 |
| 6.4   | Add structured JSON logging (request ID, job ID, timing) | P1 |
| 6.5   | Configure CORS middleware with allowlist from settings | P0 |
| 6.6   | Add rate limiting on upload endpoint (configurable) | P2 |

### Epic 7: Containerization & Deployment
> *Dockerize the service and prepare for deployment.*

| Story | Description | Priority |
| ----- | ----------- | -------- |
| 7.1   | Write `Dockerfile` with CUDA support (nvidia/cuda base image) and CPU fallback | P1 |
| 7.2   | Write `docker-compose.yml` with API, Redis, and Celery worker services | P1 |
| 7.3   | Add volume mounts for model weights, uploads, and outputs | P1 |
| 7.4   | Add environment-based config for production vs development | P1 |
| 7.5   | Write deployment guide documentation | P2 |

---

## 8. Milestone Plan

| Milestone | Epics    | Description                                                   |
| --------- | -------- | ------------------------------------------------------------- |
| **M1**    | 1, 2     | Project scaffolding + refactored CV pipeline as Python modules |
| **M2**    | 3, 4     | Working API: upload → background processing → poll status     |
| **M3**    | 5, 6     | Results serving, downloads, error handling, health check      |
| **M4**    | 7        | Docker containerization and production readiness              |

---

## 9. Tech Stack

| Layer              | Technology                                     |
| ------------------ | ---------------------------------------------- |
| **Framework**      | FastAPI + Uvicorn                              |
| **CV / ML**        | Ultralytics YOLOv8, OpenCV, PyTorch            |
| **Video Export**    | MoviePy + FFmpeg                               |
| **Task Queue**     | FastAPI BackgroundTasks (MVP) → Celery + Redis  |
| **Storage**        | Local filesystem (MVP) → S3-compatible (future) |
| **Config**         | Pydantic Settings + `.env`                     |
| **Containerization** | Docker + Docker Compose                      |
| **Python**         | 3.11+                                          |

---

## 10. Risks & Mitigations

| Risk | Impact | Mitigation |
| ---- | ------ | ---------- |
| Large video files exhaust disk/memory | High | Enforce max upload size; stream file writes; auto-cleanup via TTL |
| Long processing times block resources | High | Background workers with concurrency limits; job cancellation support |
| GPU OOM on large batches | Medium | Configurable batch size; GPU memory monitoring in health check |
| FFmpeg not installed in deployment env | Medium | Bundle FFmpeg in Docker image; validate on startup |
| Model file (`best.pt`) missing at startup | High | Fail-fast on startup with clear error message; health check validates model |

---

## 11. Out of Scope (v1)

- User authentication and multi-tenancy
- Database-backed job persistence (SQLite/PostgreSQL)
- WebSocket real-time progress streaming
- Frontend / UI
- Model retraining or fine-tuning via API
- Cloud storage (S3) integration
- Batch upload of multiple videos in one request

---

## 12. Success Criteria

1. A user can upload a video via API and receive a `job_id` within 2 seconds.
2. The background pipeline processes the video and produces identical segment outputs to the notebook.
3. A user can poll job status and see real-time progress percentage.
4. Upon completion, a user can download each cropped segment via the API.
5. The service runs in a Docker container with GPU support.

---

## 13. Folder Structure (Target)

```
JBI Detection & Segmentation/
├── app/
│   ├── __init__.py
│   ├── main.py                  # FastAPI app entry point
│   ├── config.py                # Pydantic Settings
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── jobs.py              # Job CRUD endpoints
│   │   └── health.py            # Health check endpoint
│   ├── models/
│   │   ├── __init__.py
│   │   ├── schemas.py           # Pydantic request/response models
│   │   └── job.py               # Job state model
│   ├── services/
│   │   ├── __init__.py
│   │   ├── detector.py          # YOLO detection logic
│   │   ├── segmenter.py         # Segment identification
│   │   ├── cropper.py           # Video cropping & export
│   │   └── pipeline.py          # Full pipeline orchestrator
│   └── workers/
│       ├── __init__.py
│       └── tasks.py             # Background task definitions
├── model_weights/
│   └── best.pt                  # YOLO model weights
├── storage/
│   ├── uploads/                 # Incoming video files
│   └── outputs/                 # Per-job output directories
├── tests/
│   ├── test_detector.py
│   ├── test_segmenter.py
│   ├── test_cropper.py
│   └── test_api.py
├── docs/
│   └── prd.md                   # This document
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── README.md
```
