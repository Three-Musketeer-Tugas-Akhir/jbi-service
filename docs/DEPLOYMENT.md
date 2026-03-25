# Panduan Deployment JBI Detection & Segmentation API

Dokumentasi lengkap untuk menjalankan aplikasi JBI API di lingkungan development dan production.

## 📋 Daftar Isi

- [Prasyarat](#prasyarat)
- [Struktur Project](#struktur-project)
- [Development Mode](#development-mode)
- [Production Mode](#production-mode)
- [Docker Deployment](#docker-deployment)
- [Database Migration](#database-migration)
- [Konfigurasi Environment](#konfigurasi-environment)
- [Monitoring & Logging](#monitoring--logging)
- [Troubleshooting](#troubleshooting)

---

## Prasyarat

### Hardware Requirements

| Mode | CPU | RAM | GPU | Storage |
|------|-----|-----|-----|---------|
| Development | 4 cores | 8 GB | Optional | 50 GB |
| Production | 8+ cores | 16+ GB | Recommended | 100+ GB |

### Software Requirements

- **Python**: 3.11 atau lebih tinggi
- **PostgreSQL**: 14 atau lebih tinggi
- **MinIO**: Latest (untuk object storage)
- **FFmpeg**: Terinstall di sistem
- **Docker & Docker Compose**: (Optional, untuk deployment container)

### Services yang Dibutuhkan

1. **PostgreSQL**: Database utama
2. **MinIO**: Object storage untuk video
3. **Redis**: (Opsional, untuk job queue di masa depan)

---

## Struktur Project

```
jbi-service/
├── app/                    # Kode aplikasi utama
│   ├── api/v1/            # API endpoints
│   ├── core/              # Konfigurasi dan utilitas
│   ├── db/                # Database models dan session
│   ├── services/          # Business logic
│   └── workers/           # Background workers
├── alembic/               # Database migrations
├── docs/                  # Dokumentasi
├── model_weights/         # Model YOLO (download terpisah)
├── storage/               # Uploads dan outputs
├── tests/                 # Unit dan integration tests
├── requirements.txt       # Dependencies
├── docker-compose.yml     # Docker services
├── Dockerfile             # CPU image
├── Dockerfile.gpu         # GPU image
├── run.py                 # Entry point
└── .env                   # Environment variables
```

---

## Development Mode

### 1. Clone Repository

```bash
cd /path/to/workspace
git clone <repository-url>
cd jbi-service
```

### 2. Setup Environment

```bash
# Buat virtual environment
python -m venv .venv

# Aktifkan virtual environment
# Linux/Mac:
source .venv/bin/activate
# Windows:
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt  # Untuk development tools
```

### 3. Setup Database (Local PostgreSQL)

```bash
# Install PostgreSQL (Ubuntu/Debian)
sudo apt-get install postgresql postgresql-contrib

# Buat database
sudo -u postgres psql -c "CREATE DATABASE anotasi_db;"
sudo -u postgres psql -c "CREATE USER postgres WITH PASSWORD '123456';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE anotasi_db TO postgres;"
```

### 4. Setup MinIO (Local Object Storage)

```bash
# Download dan jalankan MinIO
wget https://dl.min.io/server/minio/release/linux-amd64/minio
chmod +x minio

# Jalankan MinIO
mkdir -p ~/minio_data
./minio server ~/minio_data --console-address ":9001"

# Default credentials:
# Access Key: minioadmin
# Secret Key: minioadmin
# Console: http://localhost:9001
```

### 5. Konfigurasi Environment

```bash
# Copy file environment
cp .env.example .env

# Edit .env sesuai kebutuhan
nano .env
```

**Contoh konfigurasi development (.env)**:

```env
# Environment
ENVIRONMENT=development

# Database
DATABASE_URL=postgresql+asyncpg://postgres:123456@localhost:5432/anotasi_db
DATABASE_ECHO=true  # Log SQL queries

# MinIO
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET_NAME=anotasi-videos
MINIO_SECURE=false

# JWT (GANTI DENGAN SECRET YANG KUAT!)
JWT_SECRET_KEY=your-secret-key-here-min-32-characters-long
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=1440

# Model
MODEL_PATH=model_weights/best.pt

# Server
UVICORN_HOST=0.0.0.0
UVICORN_PORT=8000
CORS_ORIGINS=*

# Logging
LOG_LEVEL=DEBUG
```

### 6. Download Model Weights

```bash
# Buat direktori model
mkdir -p model_weights

# Download model YOLO (contoh dengan wget/curl)
# Hubungi tim untuk mendapatkan model weights
# atau letakkan file best.pt di model_weights/
```

### 7. Database Migration

```bash
# Jalankan semua migration
alembic upgrade head

# Cek status migration
alembic current
alembic history
```

### 8. Jalankan Aplikasi

```bash
# Cara 1: Menggunakan run.py (Recommended)
python run.py

# Cara 2: Menggunakan uvicorn langsung
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --log-level debug

# Cara 3: Dengan environment variables
ENVIRONMENT=development UVICORN_PORT=8000 python run.py
```

Aplikasi akan berjalan di:
- **API**: http://localhost:8000
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

### 9. Menjalankan Workers (Background Jobs)

```bash
# Terminal 1: Jalankan API server
python run.py

# Terminal 2: Jalankan Detection Worker
python run_detection_worker.py

# Terminal 3: Jalankan ASR Worker
python run_asr_worker.py
```

---

## Production Mode

### Konfigurasi Production

**File `.env.production`**:

```env
# Environment
ENVIRONMENT=production

# Database (gunakan connection pooler seperti PgBouncer untuk high load)
DATABASE_URL=postgresql+asyncpg://prod_user:strong_password@db_host:5432/anotasi_db
DATABASE_ECHO=false

# MinIO (production cluster)
MINIO_ENDPOINT=minio.cluster.local:9000
MINIO_ACCESS_KEY=production-access-key
MINIO_SECRET_KEY=production-secret-key
MINIO_BUCKET_NAME=anotasi-videos
MINIO_SECURE=true
MINIO_REGION=ap-southeast-1

# JWT (WAJIB gunakan secret yang kuat dan aman!)
JWT_SECRET_KEY=your-256-bit-secret-key-here-change-in-production
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=15
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7

# Password Hashing (naikkan rounds untuk production)
BCRYPT_ROUNDS=13

# Rate Limiting
RATE_LIMIT_LOGIN_ATTEMPTS=5
RATE_LIMIT_WINDOW_SECONDS=900

# Email (SMTP production)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=noreply@yourdomain.com
SMTP_PASSWORD=app-specific-password
FROM_EMAIL=noreply@yourdomain.com

# Model & Pipeline
MODEL_PATH=/app/model_weights/best.pt
PROCESSING_MODE=auto
BATCH_SIZE=16
MAX_CONCURRENT_JOBS=5

# Server
UVICORN_HOST=0.0.0.0
UVICORN_PORT=8000
CORS_ORIGINS=https://yourdomain.com,https://app.yourdomain.com

# Logging
LOG_LEVEL=INFO

# Sentry (Error Tracking)
SENTRY_DSN=https://your-sentry-dsn@sentry.io/project-id
```

### Menjalankan di Production

```bash
# Gunakan environment production
cp .env.production .env

# Jalankan dengan run.py (auto-detect production mode)
python run.py
```

**Perbedaan Production vs Development**:

| Fitur | Development | Production |
|-------|-------------|------------|
| Auto-reload | ✅ Enabled | ❌ Disabled |
| Access log | ✅ Uvicorn | ❌ Middleware only |
| Log level | DEBUG | INFO/WARNING |
| SQL echo | ✅ Enabled | ❌ Disabled |
| CORS | `*` (all) | Domain spesifik |
| Workers | 1 | 1 (gunakan Docker replica) |

---

## Docker Deployment

### 1. Quick Start dengan Docker Compose

```bash
# CPU Mode
docker compose --profile cpu up --build

# GPU Mode (membutuhkan NVIDIA Docker runtime)
docker compose --profile gpu up --build

# Background mode
docker compose --profile cpu up -d

# View logs
docker compose logs -f api

# Stop services
docker compose down
```

### 2. Services yang Dijalankan

Docker Compose akan menjalankan:

| Service | Port | Deskripsi |
|---------|------|-----------|
| api / api-gpu | 8000 | FastAPI application |
| db | 5432 | PostgreSQL database |
| minio | 9000 / 9001 | Object storage |

### 3. Setup MinIO Bucket (Pertama Kali)

```bash
# Akses MinIO Console di http://localhost:9001
# Login: minioadmin / minioadmin

# Buat bucket "anotasi-videos" dengan access policy "Private"
```

### 4. Database Migration di Docker

```bash
# Jalankan migration
docker compose exec api alembic upgrade head

# Cek status
docker compose exec api alembic current
```

### 5. Custom Docker Build

```bash
# Build CPU image
docker build -t jbi-api:cpu -f Dockerfile .

# Build GPU image
docker build -t jbi-api:gpu -f Dockerfile.gpu .

# Run container
docker run -d \
  --name jbi-api \
  -p 8000:8000 \
  --env-file .env \
  -v $(pwd)/model_weights:/app/model_weights:ro \
  -v jbi-uploads:/app/storage/uploads \
  jbi-api:cpu
```

---

## Database Migration

### Workflow Migration

```bash
# 1. Buat migration baru (setelah edit models)
alembic revision --autogenerate -m "deskripsi perubahan"

# 2. Review file migration yang dibuat
# File ada di: alembic/versions/xxx_deskripsi.py

# 3. Jalankan migration
alembic upgrade head

# 4. Rollback jika ada masalah
alembic downgrade -1  # 1 versi sebelumnya
alembic downgrade base  # ke awal
```

### Command Penting

```bash
# Status saat ini
alembic current

# History semua migration
alembic history --verbose

# Cek apakah ada perubahan yang belum di-migrate
alembic check

# Stamp (tandai database tanpa menjalankan migration)
alembic stamp head
```

### Migration di Production

```bash
# Backup database terlebih dahulu
pg_dump $DATABASE_URL > backup_$(date +%Y%m%d).sql

# Jalankan migration
alembic upgrade head

# Jika gagal, restore dari backup
psql $DATABASE_URL < backup_20240101.sql
```

---

## Konfigurasi Environment

### Environment Variables

| Variable | Default | Deskripsi |
|----------|---------|-----------|
| `ENVIRONMENT` | development | Mode: development/production |
| `DATABASE_URL` | - | PostgreSQL connection string |
| `JWT_SECRET_KEY` | - | Secret key untuk JWT (WAJIB diisi) |
| `MINIO_ENDPOINT` | localhost:9000 | MinIO server address |
| `MODEL_PATH` | model_weights/best.pt | Path ke model YOLO |
| `MAX_UPLOAD_SIZE_MB` | 2048 | Maximum upload file size |
| `MAX_CONCURRENT_JOBS` | 3 | Maximum parallel processing jobs |

### Security Checklist

- [ ] `JWT_SECRET_KEY` diganti dari default (min 32 karakter)
- [ ] `BCRYPT_ROUNDS` >= 12 untuk production
- [ ] Database password kuat dan unik
- [ ] MinIO credentials diganti dari default
- [ ] `CORS_ORIGINS` dibatasi ke domain spesifik (production)
- [ ] `ENVIRONMENT=production` di server production
- [ ] `LOG_LEVEL=INFO` atau `WARNING` (bukan DEBUG)

---

## Monitoring & Logging

### Log Files

```bash
# Log aplikasi (jika menggunakan file handler)
tail -f logs/app.log

# Docker logs
docker compose logs -f --tail=100 api

# Systemd logs (jika menggunakan systemd)
journalctl -u jbi-api -f
```

### Health Check

```bash
# API health
curl http://localhost:8000/api/v1/health

# Database health
curl http://localhost:8000/api/v1/health/db

# Comprehensive health
curl http://localhost:8000/api/v1/health/detailed
```

### Metrics

```bash
# System metrics (admin only)
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/admin/system/metrics

# Failed jobs
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/admin/jobs/failed
```

---

## Troubleshooting

### Masalah Umum

#### 1. Database Connection Error

```
Error: connection refused
```

**Solusi**:
```bash
# Cek PostgreSQL running
sudo systemctl status postgresql

# Cek koneksi
psql $DATABASE_URL -c "SELECT 1;"

# Cek firewall
sudo ufw allow 5432
```

#### 2. MinIO Connection Error

```
Error: Connection refused (MinIO)
```

**Solusi**:
```bash
# Cek MinIO running
curl http://localhost:9000/minio/health/live

# Cek bucket exists
mc alias set local http://localhost:9000 minioadmin minioadmin
mc ls local/anotasi-videos
```

#### 3. Model Not Found

```
Error: Model file not found: model_weights/best.pt
```

**Solusi**:
```bash
# Buat direktori dan download model
mkdir -p model_weights

# Place best.pt in model_weights/
# atau ganti MODEL_PATH di .env
```

#### 4. Permission Denied (Upload)

```
Error: Permission denied: storage/uploads
```

**Solusi**:
```bash
# Buat direktori dengan permission benar
mkdir -p storage/uploads storage/outputs
chmod -R 755 storage/
```

#### 5. Port Already in Use

```
Error: Address already in use (port 8000)
```

**Solusi**:
```bash
# Cek proses yang menggunakan port 8000
lsof -i :8000

# Kill proses atau ganti port
kill -9 <PID>
# atau
UVICORN_PORT=8001 python run.py
```

#### 6. CUDA Out of Memory (GPU)

```
RuntimeError: CUDA out of memory
```

**Solusi**:
```bash
# Kurangi batch size
BATCH_SIZE=4 python run.py

# atau gunakan CPU mode
PROCESSING_MODE=cpu python run.py
```

### Debug Mode

```bash
# Jalankan dengan log detail
LOG_LEVEL=DEBUG python run.py

# SQL query logging
DATABASE_ECHO=true python run.py
```

### Contact Support

Jika masalah berlanjut, hubungi tim development dengan informasi:
- Error message lengkap
- Log file (terakhir 100 baris)
- Environment variables (tanpa secret)
- Output `docker compose ps` (jika pakai Docker)

---

## Referensi

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [Alembic Documentation](https://alembic.sqlalchemy.org/)
- [MinIO Documentation](https://docs.min.io/)
- [Docker Documentation](https://docs.docker.com/)
