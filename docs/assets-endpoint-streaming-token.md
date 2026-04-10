# Assets Endpoint dengan Streaming Token

Dokumen ini menjelaskan perubahan pada endpoint `/api/v1/assets/*` untuk mendukung video streaming dengan token-based authentication.

---

## Overview

### Masalah Sebelumnya

1. **MinIO Pre-signed URL**: Video URL mengarah langsung ke `http://minio:9000/...` yang tidak bisa diakses dari browser
2. **401 Unauthorized**: Browser video player tidak bisa mengirim `Authorization` header
3. **403 Forbidden**: Annotator tidak bisa akses video segment karena ownership check (hanya job owner yang bisa akses)

### Solusi

Implementasi **Streaming Token** - JWT token khusus untuk video streaming yang:
- Dilewatkan via query parameter (`?token=xyz`)
- Memiliki expiry time yang configurable (default: 60 hari)
- Memberikan akses langsung ke video tanpa ownership check

---

## Cara Kerja

### 1. Token Generation

Ketika user request segment detail, backend generate streaming token:

```python
# Contoh di annotation_queue_service.py
token = streaming_token_service.generate_token(
    user_id=annotator_id,
    object_path="jobs/{job_id}/segments/segment_0000.mp4"
)
video_url = f"/api/v1/assets/{object_path}?token={token}"
```

### 2. Token Verification

Assets endpoint menerima token via query parameter:

```python
@router.get("/{path:path}")
async def get_asset(
    path: str,
    request: Request,
    token: Optional[str] = Query(None),  # Streaming token
    current_user: User = Depends(get_current_user),
):
    if token:
        # Verify streaming token (skip ownership check)
        user_id = streaming_token_service.verify_token(token, path)
        if user_id is None:
            raise HTTPException(401, "Invalid token")
    else:
        # Use JWT auth + ownership check
        ...
```

### 3. Token Payload

```json
{
    "sub": "user-uuid",
    "obj": "jobs/.../segment_0000.mp4",
    "exp": 1712345678,
    "iat": 1680809876,
    "type": "streaming"
}
```

---

## Konfigurasi

### Environment Variable

Tambahkan di `.env` file:

```bash
# Token expiry untuk video streaming (dalam hari)
# Default: 60 hari
STREAMING_TOKEN_EXPIRE_DAYS=60
```

### Config File

```python
# app/core/config.py
streaming_token_expire_days: int = 60
```

---

## API Changes

### Response Format

Semua endpoint yang return `video_url` sekarang include token:

**Before:**
```json
{
    "video_url": "http://minio:9000/anotasi-videos/jobs/.../segment_0000.mp4?X-Amz-..."
}
```

**After:**
```json
{
    "video_url": "/api/v1/assets/jobs/.../segment_0000.mp4?token=eyJhbG..."
}
```

### Endpoints Terdampak

| Endpoint | Field yang Berubah |
|----------|-------------------|
| `GET /api/v1/annotations/segments/{id}` | `video_url` |
| `GET /api/v1/annotations/queue` | `video_preview_url` |
| `GET /api/v1/asr-review/queue` | `video_url` |
| `GET /api/v1/asr-review/{id}` | `video_url` |
| `POST /api/v1/annotations/{id}/preview` | `video_url` |
| `GET /api/v1/annotation-sync/{id}/preview` | `video_url` |

### Cara Akses Video

**Option 1: Dengan Streaming Token (untuk video player)**
```bash
GET /api/v1/assets/jobs/{job_id}/segments/segment_0000.mp4?token=eyJhbG...
```

**Option 2: Dengan JWT Token (untuk API client)**
```bash
GET /api/v1/assets/jobs/{job_id}/segments/segment_0000.mp4
Authorization: Bearer {access_token}
```

---

## Security Considerations

### 1. Token Expiry

- Token expired setelah 60 hari (configurable)
- Token hanya valid untuk object path yang specific

### 2. Token Tidak Bisa Reuse

```python
# Token dibuat untuk path tertentu
if payload.get("obj") != object_path:
    return None  # Invalid
```

### 3. Ownership Check (JWT mode)

Kalau tidak pakai token, tetap ada ownership check:
- Admin: akses semua
- User: hanya job yang dia buat

### 4. Path Validation

```python
# Cegah path traversal
if '..' in path or '~' in path or path.startswith('/'):
    raise ValueError("Invalid path")
```

---

## Files yang Diubah

### New Files
- `app/services/streaming_token_service.py` - Token generation & verification

### Modified Files

| File | Perubahan |
|------|-----------|
| `app/core/config.py` | Tambah `streaming_token_expire_days` |
| `app/schemas/annotation.py` | Fix `ReviewStatusResponse` field jadi Optional |
| `app/api/v1/assets.py` | Support query token parameter |
| `app/api/v1/asr_review.py` | Pass `user_id` ke service |
| `app/services/annotation_queue_service.py` | Generate URL dengan token |
| `app/services/asr_review_service.py` | Generate URL dengan token |
| `app/services/annotation_edit_service.py` | Generate URL dengan token |
| `app/services/annotation_sync_service.py` | Generate URL dengan token |

---

## Testing

### 1. Login
```bash
curl -X POST http://152.118.31.36:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@anotasi.ai","password":"Admin123!"}'
```

### 2. Get Segment Detail
```bash
curl http://152.118.31.36:8000/api/v1/annotations/segments/{segment_id} \
  -H "Authorization: Bearer {access_token}"
```

### 3. Akses Video dengan Token
```bash
curl "http://152.118.31.36:8000/api/v1/assets/jobs/.../segment_0000.mp4?token={streaming_token}" \
  -o video.mp4
```

---

## Troubleshooting

### 401 Invalid Token
- Token sudah expired
- Token tidak cocok dengan object path

### 403 Forbidden
- Menggunakan JWT auth tapi bukan owner job
- Solusi: gunakan streaming token dari video_url

### 404 Not Found
- Video file belum tersedia di MinIO
- Path tidak valid

---

## Changelog

**2026-04-09**
- Implementasi streaming token untuk video access
- Fix ReviewStatusResponse schema validation error
- Update semua services untuk generate URL dengan token
- Assets endpoint support dual auth mode (token query param & JWT header)
