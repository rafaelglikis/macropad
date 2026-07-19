.PHONY: install install-editable sync test test-init test-wheel test-service test-systemd lint format build

install:
	@echo "Installing dependencies with uv..."
	uv sync
	@echo "✓ Dependencies installed"

install-editable:
	@echo "Installing macropad as an editable uv tool..."
	uv tool install --editable --force .
	@echo "✓ Editable macropad tool installed"

sync:
	@echo "Syncing dependencies with uv..."
	uv sync
	@echo "✓ Dependencies synced"

test:
	uv run python -m unittest discover -v

test-init:
	uv run python tests/integration/init_smoke.py

test-wheel:
	uv run python tests/integration/wheel_smoke.py

test-service:
	uv run python tests/integration/service_smoke.py

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

build:
	uv build

test-systemd:
	uv run python tests/integration/systemd_smoke.py
