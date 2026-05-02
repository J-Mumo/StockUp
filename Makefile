# StockUp Makefile - Common development commands
# Usage: make <command>

# Python paths
PYTHON = backend\venv\Scripts\python.exe
PIP = backend\venv\Scripts\pip.exe
UVICORN = backend\venv\Scripts\uvicorn.exe
ALEMBIC = backend\venv\Scripts\alembic.exe
CELERY = backend\venv\Scripts\celery.exe
PYTEST = backend\venv\Scripts\pytest.exe

# Redis
REDIS_SERVER = C:\Redis\redis-server.exe
REDIS_CLI = C:\Redis\redis-cli.exe

.PHONY: help install run migrate test redis celery

help:  ## Show help
	@echo Available commands:
	@echo   make install    - Install Python dependencies
	@echo   make run        - Start FastAPI development server
	@echo   make migrate    - Generate and apply database migrations
	@echo   make test       - Run tests
	@echo   make redis      - Start Redis server
	@echo   make celery     - Start Celery worker
	@echo   make seed       - Seed NSE companies data
	@echo   make backfill   - Backfill historical prices

install:  ## Install dependencies
	$(PIP) install -r backend\requirements.txt

run:  ## Start FastAPI dev server
	cd backend && ..\$(UVICORN) app.main:app --reload --host 0.0.0.0 --port 8000

migrate:  ## Generate migration and apply
	cd backend && ..\$(ALEMBIC) revision --autogenerate -m "$(msg)"
	cd backend && ..\$(ALEMBIC) upgrade head

migrate-up:  ## Apply pending migrations
	cd backend && ..\$(ALEMBIC) upgrade head

migrate-down:  ## Rollback last migration
	cd backend && ..\$(ALEMBIC) downgrade -1

test:  ## Run tests
	cd backend && ..\$(PYTEST) tests/ -v

redis:  ## Start Redis server
	start "" $(REDIS_SERVER)

redis-ping:  ## Check Redis is running
	$(REDIS_CLI) ping

celery:  ## Start Celery worker
	cd backend && ..\$(CELERY) -A tasks.celery_app worker --loglevel=info

celery-beat:  ## Start Celery Beat scheduler
	cd backend && ..\$(CELERY) -A tasks.celery_app beat --loglevel=info

seed:  ## Seed NSE companies
	cd backend && ..\$(PYTHON) -m cli.commands seed-nse

backfill:  ## Backfill historical prices
	cd backend && ..\$(PYTHON) -m cli.commands backfill-prices
