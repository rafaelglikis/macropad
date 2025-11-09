.PHONY: install sync systemd systemd-enable systemd-start systemd-stop systemd-status systemd-logs

SYSTEMD_USER_DIR := $(HOME)/.config/systemd/user
SERVICE_FILE := $(SYSTEMD_USER_DIR)/macropad.service
PROJECT_DIR := $(shell pwd)
UV_PATH := $(shell which uv)

install:
	@echo "Installing dependencies with uv..."
	uv sync
	@echo "✓ Dependencies installed"

sync:
	@echo "Syncing dependencies with uv..."
	uv sync
	@echo "✓ Dependencies synced"

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
	@echo "ExecStart=/bin/bash -lc '$(UV_PATH) run $(PROJECT_DIR)/main.py listen --watch'" >> $(SERVICE_FILE)
	@echo "Restart=on-failure" >> $(SERVICE_FILE)
	@echo "RestartSec=5" >> $(SERVICE_FILE)
	@echo "" >> $(SERVICE_FILE)
	@echo "[Install]" >> $(SERVICE_FILE)
	@echo "WantedBy=default.target" >> $(SERVICE_FILE)
	@systemctl --user daemon-reload
	@echo "✓ Systemd service created at $(SERVICE_FILE)"
	@echo ""
	@echo "To enable and start the service, run:"
	@echo "  make systemd-enable"
	@echo "  make systemd-start"

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