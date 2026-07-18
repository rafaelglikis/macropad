.PHONY: install install-editable sync test test-wheel build systemd enable start restart stop status logs

SYSTEMD_USER_DIR := $(HOME)/.config/systemd/user
SERVICE_FILE := $(SYSTEMD_USER_DIR)/macropad.service
PROJECT_DIR := $(CURDIR)

install:
	@echo "Installing dependencies with uv..."
	uv sync
	@echo "✓ Dependencies installed"

install-editable:
	@echo "Installing macropad as an editable uv tool..."
	uv tool install --editable --force "$(PROJECT_DIR)"
	@echo "✓ Editable macropad tool installed"

sync:
	@echo "Syncing dependencies with uv..."
	uv sync
	@echo "✓ Dependencies synced"

test:
	uv run python -m unittest discover -v

test-wheel:
	uv run python tests/wheel_smoke.py

build:
	uv build

systemd:
	@echo "Creating systemd user service..."
	@mkdir -p $(SYSTEMD_USER_DIR)
	@echo "[Unit]" > $(SERVICE_FILE)
	@echo "Description=Macropad Keyboard Interceptor" >> $(SERVICE_FILE)
	@echo "After=default.target" >> $(SERVICE_FILE)
	@echo "" >> $(SERVICE_FILE)
	@echo "[Service]" >> $(SERVICE_FILE)
	@echo "Type=simple" >> $(SERVICE_FILE)
	@echo "WorkingDirectory=$(PROJECT_DIR)" >> $(SERVICE_FILE)
	@echo "Environment=PYTHONUNBUFFERED=1" >> $(SERVICE_FILE)
	@echo "ExecStart=$(PROJECT_DIR)/.venv/bin/macropad listen --watch" >> $(SERVICE_FILE)
	@echo "KillMode=mixed" >> $(SERVICE_FILE)
	@echo "TimeoutStopSec=10" >> $(SERVICE_FILE)
	@echo "Restart=on-failure" >> $(SERVICE_FILE)
	@echo "RestartSec=5" >> $(SERVICE_FILE)
	@echo "" >> $(SERVICE_FILE)
	@echo "[Install]" >> $(SERVICE_FILE)
	@echo "WantedBy=default.target" >> $(SERVICE_FILE)
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
