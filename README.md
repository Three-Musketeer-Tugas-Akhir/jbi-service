# JBI Detection & Segmentation API

API untuk deteksi dan segmentasi overlay JBI (Jawa Bali Indonesia) dalam video berita, dengan pipeline ASR (Automatic Speech Recognition) dan sistem anotasi kolaboratif.

## ✨ Fitur Utama

- **🔍 JBI Detection**: Deteksi otomatis overlay JBI menggunakan YOLO
- **✂️ Video Segmentation**: Segmentasi video berdasarkan deteksi JBI
- **🎙️ ASR Pipeline**: Transkripsi otomatis dengan Whisper
- **📝 Annotation Workflow**: Sistem anotasi dengan draft, review, dan approval
- **👥 RBAC**: Role-based access control (admin, annotator, curator)
- **📊 Monitoring**: Health checks, metrics, dan logging komprehensif

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL 14+
- MinIO (object storage)
- FFmpeg

### 1. Install Dependencies

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Setup Environment

```bash
cp .env.example .env
# Edit .env sesuai konfigurasi Anda
```

### 3. Setup Database

```bash
# Buat database PostgreSQL
createdb anotasi_db

# Jalankan migration
alembic upgrade head
```

### 4. Run Application

```bash
python run.py
```

Akses aplikasi:
- API: http://localhost:8000
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### 5. Run Workers (Background Jobs)

```bash
# Terminal 1: API Server
python run.py

# Terminal 2: Detection Worker
python run_detection_worker.py

# Terminal 3: ASR Worker
python run_asr_worker.py
```

## 🐳 Docker Deployment

```bash
# CPU Mode
docker compose --profile cpu up --build

# GPU Mode
docker compose --profile gpu up --build
```

Lihat [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) untuk detail lengkap deployment.

## 📚 Dokumentasi

- [Deployment Guide](docs/DEPLOYMENT.md) - Panduan deployment development & production
- [Swagger Documentation](docs/SWAGGER.md) - Dokumentasi API dengan Swagger

## 🏗️ Arsitektur

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Client    │────▶│  FastAPI    │────▶│  PostgreSQL │
└─────────────┘     └─────────────┘     └─────────────┘
                           │
                           ▼
                    ┌─────────────┐
                    │    MinIO    │
                    │   (Video)   │
                    └─────────────┘
                           │
                           ▼
              ┌────────────────────────┐
              │     Background Workers  │
              │  ┌──────────────────┐  │
              │  │ Detection Worker │  │
              │  │ ASR Worker       │  │
              │  └──────────────────┘  │
              └────────────────────────┘
```

## 🔧 Konfigurasi

### Environment Variables Penting

| Variable | Deskripsi |
|----------|-----------|
| `ENVIRONMENT` | development / production |
| `DATABASE_URL` | PostgreSQL connection string |
| `JWT_SECRET_KEY` | Secret key untuk JWT (wajib diisi) |
| `MINIO_ENDPOINT` | MinIO server address |
| `MODEL_PATH` | Path ke model YOLO |

## 🧪 Testing

```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Run tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html
```

## 📁 Struktur Project

```
jbi-service/
├── app/
│   ├── api/v1/          # API endpoints
│   ├── core/            # Config & swagger
│   ├── db/              # Database models
│   ├── services/        # Business logic
│   └── workers/         # Background jobs
├── alembic/             # Database migrations
├── docs/                # Documentation
├── tests/               # Test files
├── requirements.txt     # Dependencies
└── docker-compose.yml   # Docker services
```

## 🛡️ Security

- JWT authentication dengan refresh token
- Password hashing dengan bcrypt
- Rate limiting pada endpoint login
- Role-based access control (RBAC)
- Audit logging untuk semua aksi penting

## 📄 License

MIT License - lihat [LICENSE](LICENSE) untuk detail.

## 🤝 Kontribusi

Kontribusi sangat diterima! Silakan buat issue atau pull request.

## 📞 Support

Untuk bantuan lebih lanjut:
- Email: support@jbi-api.local
- Dokumentasi: /docs (Swagger UI)
- Issues: [GitHub Issues](https://github.com/your-repo/issues)
