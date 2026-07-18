.PHONY: install install-editable sync test test-wheel test-service test-systemd lint format build render-systemd systemd enable start restart stop status logs

SYSTEMD_USER_DIR := $(HOME)/.config/systemd/user
SERVICE_FILE := $(SYSTEMD_USER_DIR)/macropad.service
RENDERED_SERVICE_FILE := tmp/macropad.service

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

render-systemd:
	@echo "Rendering systemd user service..."
	uv run python tools/render_systemd_unit.py

test-systemd: render-systemd
	systemd-analyze --user verify "$(RENDERED_SERVICE_FILE)"
	@echo "✓ Systemd user service is valid"

systemd: test-systemd
	@echo "Creating systemd user service..."
	install -Dm644 "$(RENDERED_SERVICE_FILE)" "$(SERVICE_FILE)"
	@systemctl --user daemon-reload
	@echo "✓ Systemd service created at $(SERVICE_FILE)"
	@echo ""
	@echo "To enable and start the service, run:"
	@echo "  make enable"
	@echo "  make start"

enable:
	systemctl --user enable macropad.service
	@echo "✓ Service enabled (will start on login)"

start:
	systemctl --user start macropad.service
	@echo "✓ Service started"

restart:
	systemctl --user restart macropad.service
	@echo "✓ Service started"

stop:
	systemctl --user stop macropad.service
	@echo "✓ Service stopped"

status:
	systemctl --user status macropad.service

logs:
	journalctl --user -u macropad.service -f
