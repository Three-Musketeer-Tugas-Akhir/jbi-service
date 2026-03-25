# JBI Detection & Segmentation API - Makefile
# Common development tasks

.PHONY: help install dev-install run dev run-workers test lint format migrate db-upgrade db-downgrade docker-build docker-up docker-down clean

# Default target
help:
	@echo "Available commands:"
	@echo "  make install       - Install production dependencies"
	@echo "  make dev-install   - Install development dependencies"
	@echo "  make run           - Run production server"
	@echo "  make dev           - Run development server with auto-reload"
	@echo "  make run-workers   - Run background workers (detection + ASR)"
	@echo "  make test          - Run all tests"
	@echo "  make test-cov      - Run tests with coverage"
	@echo "  make lint          - Run linters (ruff, mypy)"
	@echo "  make format        - Format code with black"
	@echo "  make migrate       - Create new migration (prompt for message)"
	@echo "  make db-upgrade    - Run database migrations"
	@echo "  make db-downgrade  - Rollback last migration"
	@echo "  make docker-build  - Build Docker images"
	@echo "  make docker-up     - Start Docker services"
	@echo "  make docker-down   - Stop Docker services"
	@echo "  make clean         - Clean cache and temporary files"

# Installation
install:
	pip install -r requirements.txt

dev-install: install
	pip install -r requirements-dev.txt

# Running
run:
	ENVIRONMENT=production python run.py

dev:
	ENVIRONMENT=development python run.py

run-workers:
	@echo "Starting workers in separate processes..."
	@trap 'kill %1; kill %2' SIGINT; \
	python run_detection_worker.py & \
	python run_asr_worker.py & \
	wait

# Testing
test:
	pytest -v

test-cov:
	pytest --cov=app --cov-report=html --cov-report=term

# Code quality
lint:
	ruff check app tests
	mypy app --ignore-missing-imports

format:
	black app tests
	ruff check --fix app tests

# Database migrations
migrate:
	@read -p "Enter migration message: " msg; \
	alembic revision --autogenerate -m "$$msg"

db-upgrade:
	alembic upgrade head

db-downgrade:
	alembic downgrade -1

db-status:
	alembic current
	alembic history --verbose

# Docker
docker-build:
	docker compose --profile cpu build

docker-build-gpu:
	docker compose --profile gpu build

docker-up:
	docker compose --profile cpu up -d

docker-up-gpu:
	docker compose --profile gpu up -d

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f api

# Utility
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	rm -rf storage/uploads/* storage/outputs/* 2>/dev/null || true

# Setup (first time)
setup:
	@echo "Setting up development environment..."
	python -m venv .venv
	@echo "Virtual environment created. Activate with: source .venv/bin/activate"
	@echo "Then run: make dev-install"
	@echo "Copy .env.example to .env and configure"
	@echo "Run: make db-upgrade"

# Health check
health:
	@curl -s http://localhost:8000/api/v1/health | python -m json.tool

# Generate API client (optional)
generate-client:
	@echo "Generating API client from OpenAPI spec..."
	@curl -s http://localhost:8000/openapi.json > openapi.json
	@echo "OpenAPI spec saved to openapi.json"
