# API Documentation

**Base URL:** `http://localhost:8000/api/v1`

**Interactive docs:** `http://localhost:8000/docs` (Swagger UI)

All responses use `Content-Type: application/json` unless otherwise noted.

---

## Table of Contents

1. [Create Job](#1-create-job)
2. [List Jobs](#2-list-jobs)
3. [Get Job Status](#3-get-job-status)
4. [Cancel Job](#4-cancel-job)
5. [Get Job Results](#5-get-job-results)
6. [Download Segment](#6-download-segment)
7. [Health Check](#7-health-check)
8. [Job Lifecycle](#8-job-lifecycle)
9. [Error Responses](#9-error-responses)
10. [Client Polling Guide](#10-client-polling-guide)

---

## 1. Create Job

Upload a video file or provide a public URL to start a JBI detection job.

```
POST /api/v1/jobs
Content-Type: multipart/form-data
```

### Parameters

| Field  | Type           | Required | Description                                      |
| ------ | -------------- | -------- | ------------------------------------------------ |
| `file` | binary (file)  | Either   | Video file upload (multipart)                    |
| `url`  | string (form)  | Either   | Public URL to a video file                       |

- At least one of `file` or `url` must be provided.
- If both are provided, `file` takes priority.
- Accepted extensions: `.mp4`, `.avi`, `.mkv`, `.mov`
- Maximum file size: 2048 MB (configurable)

### Response — `202 Accepted`

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "queued",
  "created_at": "2026-02-11T10:00:00.000000Z"
}
```

### Errors

| Status | Condition                          | Example Detail                                               |
| ------ | ---------------------------------- | ------------------------------------------------------------ |
| 400    | Neither file nor url provided      | `"Either 'file' or 'url' must be provided"`                 |
| 400    | Invalid file extension             | `"File extension '.wmv' not allowed. Accepted: .mp4, ..."` |
| 400    | File too large                     | `"File size 2500.0 MB exceeds maximum 2048 MB"`            |
| 400    | Not a valid video                  | `"File is not a valid video or cannot be opened"`           |
| 400    | URL unreachable                    | `"Cannot connect to URL: https://..."`                      |
| 400    | URL timeout                        | `"Connection timed out: https://..."`                       |
| 400    | URL returns error                  | `"URL returned HTTP 404"`                                   |
| 400    | Downloaded file exceeds max size   | `"Download exceeds maximum size of 2048 MB"`               |
| 422    | Missing form data                  | FastAPI validation error                                     |
| 500    | Disk write failure                 | `"Failed to save uploaded file"`                            |

### Examples

**File upload:**

```bash
curl -X POST http://localhost:8000/api/v1/jobs \
  -F "file=@video.mp4"
```

**URL ingestion:**

```bash
curl -X POST http://localhost:8000/api/v1/jobs \
  -F "url=https://example.com/broadcast.mp4"
```

---

## 2. List Jobs

Retrieve a paginated list of all jobs, optionally filtered by status.

```
GET /api/v1/jobs
```

### Query Parameters

| Parameter | Type   | Default | Description                                                     |
| --------- | ------ | ------- | --------------------------------------------------------------- |
| `status`  | string | (none)  | Filter by status: `queued`, `processing`, `completed`, `failed`, `cancelled` |
| `limit`   | int    | 20      | Max number of jobs to return (1–100)                            |
| `offset`  | int    | 0       | Number of jobs to skip for pagination                           |

### Response — `200 OK`

```json
{
  "jobs": [
    {
      "job_id": "550e8400-e29b-41d4-a716-446655440000",
      "status": "processing",
      "progress": {
        "phase": "detection",
        "current": 340,
        "total": 3400,
        "percent": 10.0
      },
      "error": null,
      "created_at": "2026-02-11T10:00:00.000000Z",
      "updated_at": "2026-02-11T10:02:15.000000Z"
    },
    {
      "job_id": "660f9500-f39c-52e5-b827-557766551111",
      "status": "completed",
      "progress": null,
      "error": null,
      "created_at": "2026-02-11T09:00:00.000000Z",
      "updated_at": "2026-02-11T09:30:00.000000Z"
    }
  ],
  "total": 42,
  "limit": 20,
  "offset": 0
}
```

**Filtered by status:**

```bash
curl "http://localhost:8000/api/v1/jobs?status=completed&limit=10"
```

**Empty result:**

```json
{
  "jobs": [],
  "total": 0,
  "limit": 20,
  "offset": 0
}
```

### Response Fields

| Field    | Type              | Description                                              |
| -------- | ----------------- | -------------------------------------------------------- |
| `jobs`   | array             | Array of job status objects (same shape as Get Job Status) |
| `total`  | int               | Total number of jobs matching the filter (before pagination) |
| `limit`  | int               | Page size used                                           |
| `offset` | int               | Offset used                                              |

Each item in `jobs` follows the same schema as the [Get Job Status](#3-get-job-status) response.

### Errors

| Status | Condition          | Detail                                                                 |
| ------ | ------------------ | ---------------------------------------------------------------------- |
| 400    | Invalid status     | `"Invalid status 'foo'. Must be one of: cancelled, completed, ..."` |

### Examples

**All jobs (default pagination):**

```bash
curl http://localhost:8000/api/v1/jobs
```

**Second page of failed jobs:**

```bash
curl "http://localhost:8000/api/v1/jobs?status=failed&limit=10&offset=10"
```

---

## 3. Get Job Status

Poll the current status and processing progress of a job.

```
GET /api/v1/jobs/{job_id}
```

### Path Parameters

| Parameter | Type   | Description    |
| --------- | ------ | -------------- |
| `job_id`  | string | UUID of the job |

### Response — `200 OK`

**Queued:**

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "queued",
  "progress": null,
  "error": null,
  "created_at": "2026-02-11T10:00:00.000000Z",
  "updated_at": "2026-02-11T10:00:00.000000Z"
}
```

**Processing (detection phase):**

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "processing",
  "progress": {
    "phase": "detection",
    "current": 340,
    "total": 3400,
    "percent": 10.0
  },
  "error": null,
  "created_at": "2026-02-11T10:00:00.000000Z",
  "updated_at": "2026-02-11T10:02:15.000000Z"
}
```

**Processing (cropping phase):**

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "processing",
  "progress": {
    "phase": "cropping",
    "current": 2,
    "total": 5,
    "percent": 40.0
  },
  "error": null,
  "created_at": "2026-02-11T10:00:00.000000Z",
  "updated_at": "2026-02-11T10:15:30.000000Z"
}
```

**Completed:**

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "progress": null,
  "error": null,
  "created_at": "2026-02-11T10:00:00.000000Z",
  "updated_at": "2026-02-11T10:20:00.000000Z"
}
```

**Failed:**

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "failed",
  "progress": null,
  "error": "[detection] Cannot open video file: /storage/uploads/abc.mp4",
  "created_at": "2026-02-11T10:00:00.000000Z",
  "updated_at": "2026-02-11T10:00:05.000000Z"
}
```

### Response Fields

| Field                | Type              | Description                                         |
| -------------------- | ----------------- | --------------------------------------------------- |
| `job_id`             | string            | UUID of the job                                     |
| `status`             | string            | One of: `queued`, `processing`, `completed`, `failed`, `cancelled` |
| `progress`           | object \| null    | Present only when `status` is `processing`          |
| `progress.phase`     | string            | Current phase: `detection`, `segmentation`, or `cropping` |
| `progress.current`   | int               | Current step in the phase                           |
| `progress.total`     | int               | Total steps in the phase                            |
| `progress.percent`   | float             | Completion percentage (0.0–100.0)                   |
| `error`              | string \| null    | Error message when `status` is `failed`             |
| `created_at`         | string (ISO 8601) | Job creation timestamp (UTC)                        |
| `updated_at`         | string (ISO 8601) | Last status update timestamp (UTC)                  |

### Errors

| Status | Condition     | Detail                         |
| ------ | ------------- | ------------------------------ |
| 404    | Job not found | `"Job '{job_id}' not found"` |

---

## 4. Cancel Job

Cancel a queued or in-progress job. Queued jobs are cancelled immediately. Processing jobs are marked as cancelled and the background worker stops cooperatively on its next progress callback.

```
DELETE /api/v1/jobs/{job_id}
```

### Path Parameters

| Parameter | Type   | Description    |
| --------- | ------ | -------------- |
| `job_id`  | string | UUID of the job |

### Response — `200 OK`

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "cancelled"
}
```

### Errors

| Status | Condition                    | Detail                                                                 |
| ------ | ---------------------------- | ---------------------------------------------------------------------- |
| 404    | Job not found                | `"Job '{job_id}' not found"`                                         |
| 409    | Job already in terminal state | `"Job '{job_id}' is already 'completed' and cannot be cancelled"` |

### Example

```bash
curl -X DELETE http://localhost:8000/api/v1/jobs/550e8400-e29b-41d4-a716-446655440000
```

---

## 5. Get Job Results

Retrieve structured detection and segmentation results for a completed job.

```
GET /api/v1/jobs/{job_id}/results
```

### Path Parameters

| Parameter | Type   | Description    |
| --------- | ------ | -------------- |
| `job_id`  | string | UUID of the job |

### Response — `200 OK`

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
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
      "bbox": {
        "x_min": 120.5,
        "y_min": 450.0,
        "width": 800.0,
        "height": 120.0
      },
      "download_url": "/api/v1/jobs/550e8400-.../segments/0/download"
    },
    {
      "index": 1,
      "start_time": "0:10:30",
      "end_time": "0:12:15",
      "start_seconds": 630,
      "end_seconds": 735,
      "duration_seconds": 105,
      "bbox": {
        "x_min": 118.0,
        "y_min": 448.5,
        "width": 802.0,
        "height": 122.0
      },
      "download_url": "/api/v1/jobs/550e8400-.../segments/1/download"
    }
  ]
}
```

**No detections found:**

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "video_metadata": {
    "fps": 30.0,
    "total_frames": 9000,
    "duration_seconds": 300.0
  },
  "detection_summary": {
    "total_seconds_scanned": 300,
    "seconds_with_detection": 0
  },
  "segments": []
}
```

### Response Fields

| Field                                         | Type   | Description                                          |
| --------------------------------------------- | ------ | ---------------------------------------------------- |
| `video_metadata.fps`                          | float  | Video frame rate                                     |
| `video_metadata.total_frames`                 | int    | Total frame count                                    |
| `video_metadata.duration_seconds`             | float  | Video duration in seconds                            |
| `detection_summary.total_seconds_scanned`     | int    | Total seconds analyzed                               |
| `detection_summary.seconds_with_detection`    | int    | Seconds where JBI was detected                       |
| `segments[].index`                            | int    | Zero-based segment index                             |
| `segments[].start_time`                       | string | Start time as `H:MM:SS`                              |
| `segments[].end_time`                         | string | End time as `H:MM:SS`                                |
| `segments[].start_seconds`                    | int    | Start time in seconds                                |
| `segments[].end_seconds`                      | int    | End time in seconds                                  |
| `segments[].duration_seconds`                 | int    | Segment duration in seconds                          |
| `segments[].bbox.x_min`                       | float  | Bounding box left edge (pixels)                      |
| `segments[].bbox.y_min`                       | float  | Bounding box top edge (pixels)                       |
| `segments[].bbox.width`                       | float  | Bounding box width (pixels)                          |
| `segments[].bbox.height`                      | float  | Bounding box height (pixels)                         |
| `segments[].download_url`                     | string | Relative URL to download the cropped segment         |

### Errors

| Status | Condition                 | Detail                                                                       |
| ------ | ------------------------- | ---------------------------------------------------------------------------- |
| 404    | Job not found             | `"Job '{job_id}' not found"`                                               |
| 409    | Job not completed         | `"Job '{job_id}' is 'processing' — results are only available for completed jobs"` |
| 500    | Result data missing       | `"Job '{job_id}' is completed but result data is missing"`                 |

---

## 6. Download Segment

Stream a cropped MP4 segment file.

```
GET /api/v1/jobs/{job_id}/segments/{index}/download
```

### Path Parameters

| Parameter | Type   | Description              |
| --------- | ------ | ------------------------ |
| `job_id`  | string | UUID of the job          |
| `index`   | int    | Zero-based segment index |

### Response — `200 OK`

```
Content-Type: video/mp4
Content-Disposition: attachment; filename="segment_000000.mp4"
Content-Length: 2458632

<binary MP4 data>
```

The file is streamed asynchronously and not loaded into memory.

### Errors

| Status | Condition                | Detail                                                                       |
| ------ | ------------------------ | ---------------------------------------------------------------------------- |
| 404    | Job not found            | `"Job '{job_id}' not found"`                                               |
| 409    | Job not completed        | `"Job '{job_id}' is 'processing' — downloads are only available for completed jobs"` |
| 404    | Segment index out of range | `"Segment index 5 not found — job has 3 segments (0–2)"`               |
| 404    | File missing on disk     | `"Segment file not found on disk — it may have been cleaned up"`           |

### Example

```bash
curl -o segment_000000.mp4 \
  http://localhost:8000/api/v1/jobs/550e8400-.../segments/0/download
```

Verify headers:

```bash
curl -I http://localhost:8000/api/v1/jobs/550e8400-.../segments/0/download
# content-type: video/mp4
# content-disposition: attachment; filename="segment_000000.mp4"
# content-length: 2458632
```

---

## 7. Health Check

Check service health including model status, GPU availability, and disk space.

```
GET /api/v1/health
```

### Response — `200 OK`

```json
{
  "status": "healthy",
  "model_loaded": true,
  "gpu_available": true,
  "gpu_name": "NVIDIA GeForce RTX 3060",
  "disk_free_gb": 45.2
}
```

### Response Fields

| Field          | Type           | Description                                               |
| -------------- | -------------- | --------------------------------------------------------- |
| `status`       | string         | `"healthy"`, `"degraded"`, or `"unhealthy"`               |
| `model_loaded` | bool           | Whether the YOLO model has been loaded                    |
| `gpu_available`| bool           | Whether CUDA GPU is available                             |
| `gpu_name`     | string \| null | GPU device name (null if no GPU)                          |
| `disk_free_gb` | float          | Free disk space on the storage partition (GB)             |

### Status Logic

| Condition                                   | Status       |
| ------------------------------------------- | ------------ |
| Model loaded and disk space > 1 GB          | `healthy`    |
| GPU mode configured but no GPU available    | `degraded`   |
| Model not loaded or disk space < 1 GB       | `unhealthy`  |

---

## 8. Job Lifecycle

### Status Flow

```
queued → processing → completed
                   → failed
queued → cancelled
processing → cancelled
```

### States

| Status       | Description                                               |
| ------------ | --------------------------------------------------------- |
| `queued`     | Job created, waiting for background worker to start       |
| `processing` | Pipeline is running (detection → segmentation → cropping) |
| `completed`  | All segments exported, results available                  |
| `failed`     | Pipeline encountered an error (see `error` field)         |
| `cancelled`  | Job was cancelled by user via `DELETE` endpoint           |

### Terminal States

`completed`, `failed`, and `cancelled` are terminal — no further transitions.

### Automatic Cleanup

Jobs in terminal states are automatically deleted after `JOB_TTL_HOURS` (default: 24 hours). Cleanup runs every `CLEANUP_INTERVAL_MINUTES` (default: 30 minutes). Deleted data includes:

- The job record (subsequent status queries return 404)
- The uploaded video file
- The output directory with all cropped segments

Jobs still in `processing` state are never deleted by the cleanup scheduler, regardless of age.

---

## 9. Error Responses

All errors use a consistent JSON structure:

```json
{
  "detail": "Human-readable error message"
}
```

For validation errors (422):

```json
{
  "detail": [
    {
      "loc": ["body", "file"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

### Common HTTP Status Codes

| Code | Meaning                                                     |
| ---- | ----------------------------------------------------------- |
| 200  | Success                                                     |
| 202  | Job created, processing started in background               |
| 400  | Bad request (invalid input, validation failure)             |
| 404  | Resource not found (job, segment, file)                     |
| 409  | Conflict (job in wrong state for the requested action)      |
| 422  | Validation error (missing required fields)                  |
| 500  | Internal server error                                       |

---

## 10. Client Polling Guide

Recommended polling pattern after creating a job:

```
1. POST /api/v1/jobs              → get job_id (202)
2. Loop:
   a. GET /api/v1/jobs/{job_id}
   b. status == "queued"      → wait 2s, repeat
   c. status == "processing"  → display progress, wait 1s, repeat
   d. status == "completed"   → GET /results → done
   e. status == "failed"      → show error → stop
   f. status == "cancelled"   → show cancelled → stop
```

### Python Example

```python
import time
import requests

BASE = "http://localhost:8000/api/v1"

# 1. Upload
resp = requests.post(f"{BASE}/jobs", files={"file": open("video.mp4", "rb")})
job_id = resp.json()["job_id"]
print(f"Job created: {job_id}")

# 2. Poll
while True:
    resp = requests.get(f"{BASE}/jobs/{job_id}")
    data = resp.json()

    if data["status"] == "processing" and data["progress"]:
        p = data["progress"]
        print(f"  [{p['phase']}] {p['percent']}%")
    elif data["status"] == "completed":
        print("Done!")
        break
    elif data["status"] == "failed":
        print(f"Failed: {data['error']}")
        break
    elif data["status"] == "cancelled":
        print("Cancelled")
        break

    time.sleep(1)

# 3. Get results
if data["status"] == "completed":
    results = requests.get(f"{BASE}/jobs/{job_id}/results").json()
    print(f"Found {len(results['segments'])} segments")

    # 4. Download each segment
    for seg in results["segments"]:
        url = f"http://localhost:8000{seg['download_url']}"
        filename = f"segment_{seg['index']:06d}.mp4"
        with open(filename, "wb") as f:
            f.write(requests.get(url).content)
        print(f"  Downloaded {filename}")
```

### JavaScript (fetch) Example

```javascript
const BASE = "http://localhost:8000/api/v1";

// 1. Upload
const form = new FormData();
form.append("file", fileInput.files[0]);
const createResp = await fetch(`${BASE}/jobs`, { method: "POST", body: form });
const { job_id } = await createResp.json();

// 2. Poll
let status = "queued";
while (status === "queued" || status === "processing") {
  await new Promise((r) => setTimeout(r, 1000));
  const statusResp = await fetch(`${BASE}/jobs/${job_id}`);
  const data = await statusResp.json();
  status = data.status;

  if (data.progress) {
    console.log(`[${data.progress.phase}] ${data.progress.percent}%`);
  }
}

// 3. Get results
if (status === "completed") {
  const results = await fetch(`${BASE}/jobs/${job_id}/results`);
  const { segments } = await results.json();
  console.log(`Found ${segments.length} segments`);
}
```
