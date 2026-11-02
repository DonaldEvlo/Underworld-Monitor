.PHONY: up migrate test test-unit test-integration lint typecheck collection-report

up:
	docker compose up --build

migrate:
	docker compose exec backend alembic upgrade head

# Toute la suite. Les tests d'integration tournent contre la base de
# developpement mais dans une transaction ANNULEE a la fin de chaque test
# (backend/app/tests/integration/conftest.py) : aucune ecriture ne survit.
test:
	docker compose exec backend pytest

test-unit:
	docker compose exec backend pytest app/tests/unit

test-integration:
	docker compose exec backend pytest app/tests/integration

lint:
	docker compose exec backend sh -c "ruff check . && black --check ."

# Perimetre progressif : voir [tool.mypy] dans backend/pyproject.toml.
typecheck:
	docker compose exec backend mypy

# Garde-fou post-collecte : signale toute source dont last_collected_at est
# renseigne mais qui n'a aucun document en base (collecte qui n'a pas
# persiste) -- voir backend/app/scripts/collection_report.py.
collection-report:
	docker compose exec backend python -m app.scripts.collection_report --active-only
