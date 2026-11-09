.PHONY: install test test-integration lint typecheck check build-web verify-web scan-web clean

install:
	uv sync --extra dev

test:
	uv run pytest

test-integration:
	HAIBOX_RUN_INTEGRATION=1 uv run pytest -m integration -vv

lint:
	uv run ruff check .

typecheck:
	uv run mypy src

check: lint typecheck test

build-web:
	./scripts/build-image.sh web-security

verify-web:
	./scripts/verify-image.sh web-security

scan-web:
	uv run haibox image scan web-security

clean:
	rm -rf .venv .pytest_cache .ruff_cache .mypy_cache dist build
