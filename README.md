# Macropad

Turn every keyboard into a macropad.

## Install

Install the system dependencies required to build the Python DBus bindings:

Debian/Ubuntu:

```bash
sudo apt install libdbus-1-dev libglib2.0-dev
```

Fedora:

```bash
sudo dnf install dbus-devel glib2-devel
```

Then install the Python dependencies:

```bash
make
```

Install `macropad` as a user-level editable command when developing locally:

```bash
make install-editable
```

## Usage

Listen using profiles from the default configuration directory:

```bash
uv run macropad listen
```

Detect a newly connected keyboard and generate a profile:

```bash
uv run macropad detect --generate-profile
```

The module entry point is also available:

```bash
uv run python -m macropad --help
```

## Service

Install and start the systemd user service:

```bash
make systemd
make enable
make start
```

Use `make status`, `make logs`, and `make restart` to manage it.

## Development

```bash
make test
make test-wheel
make build
```
