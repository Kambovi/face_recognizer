.PHONY: up down build seed smoke test test-backend test-kiosk test-frontend bench lint fmt logs ps clean

up:
	docker compose up -d --build
	@echo "Waiting for API health..."
	@for i in $$(seq 1 60); do \
		if curl -fs http://localhost:8000/api/v1/health > /dev/null 2>&1; then echo "API is up."; exit 0; fi; \
		sleep 2; \
	done; \
	echo "API did not become healthy in time" >&2; exit 1

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f

ps:
	docker compose ps

# --- Demo data --------------------------------------------------------------
seed:
	docker compose exec -T api python scripts/seed_demo.py

# --- End-to-end smoke test ---------------------------------------------------
smoke:
	docker compose exec -T api python scripts/smoke.py

# --- Test suites --------------------------------------------------------------
test: test-backend test-kiosk test-frontend

test-backend:
	cd backend && python3 -m venv .venv-test 2>/dev/null || true
	cd backend && . .venv-test/bin/activate && pip install -q -r requirements-dev.txt && pip install -q onnxruntime==1.19.2 && DATABASE_URL_SYNC=sqlite:///./test.db DATABASE_URL=sqlite+aiosqlite:///./test.db EMBEDDING_ENCRYPTION_KEY=Uh6Z8s4y6b0e7z3v1c9x2q5w8n1m4k7j0h3g6f9d2s5= JWT_SECRET=test_secret KIOSK_SERVICE_TOKEN=test_token python -m pytest tests/ -v

test-kiosk:
	cd kiosk && python3 -m venv .venv-test 2>/dev/null || true
	cd kiosk && . .venv-test/bin/activate && pip install -q -r requirements-dev.txt && pip install -q onnxruntime==1.19.2 && python -m pytest tests/ -v

test-frontend:
	cd frontend && npm install && npm run build && npm run test -- --run

# --- Benchmark ----------------------------------------------------------------
bench:
	docker compose exec -T kiosk python -m kiosk.bench

lint:
	cd backend && ruff check . && mypy app
	cd kiosk && ruff check . && mypy kiosk
	cd frontend && npm run lint

fmt:
	cd backend && ruff format .
	cd kiosk && ruff format .

clean:
	docker compose down -v
	rm -rf backend/.venv-test kiosk/.venv-test frontend/node_modules frontend/dist
