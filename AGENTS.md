# Repository Guidance

## Environment And Commands

- This is a Linux-only Python 3.10+ project using `uv`; native DBus headers are required (`libdbus-1-dev libglib2.0-dev` on Debian/Ubuntu, `dbus-devel glib2-devel` on Fedora).
- Create/update the project `.venv` with `make` or `uv sync`. Use `uv sync --frozen` and `uv lock --check` when reproducing CI; run `uv lock` only after dependency metadata changes.
- Run one test with `uv run python -m unittest tests.test_handlers.KeyboardHandlerLayerTests.test_down_only_binding_repeats_for_key_hold_events`; run a module with `uv run python -m unittest tests.test_handlers`.
- Before finalizing Python changes, run `make format`, `make lint`, and `make test` in that order. Ruff is pinned in the dev dependency group and enforces 100-column, single-quote formatting plus `E4`, `E7`, `E9`, `F`, `I`, and `B` rules.
- Integration scripts live under `tests/integration/` and are intentionally excluded from normal `unittest` discovery. Run `make test-wheel` for packaging/assets/metadata/entry points, `make test-service` for headless startup and graceful SIGTERM, and `make test-systemd` for unit rendering. `make test-wheel` creates an isolated environment and may need network access and native build dependencies.
- `make build` creates ignored artifacts under `dist/`; systemd rendering creates ignored `tmp/macropad.service`. Do not edit or commit either generated directory.
- CI tests Python 3.10 through 3.14, then checks lint, lockfile, wheel installation, service lifecycle, systemd rendering, and distribution artifacts.

## Runtime Architecture

- Both `macropad` and `python -m macropad` enter through `src/macropad/cli.py`. The CLI owns Watchdog reload requests and is the only component that calls supervisor reloads.
- `ProfileSupervisor` validates and merges the complete candidate configuration before reconciliation, then owns one worker slot per keyboard name, process lifecycle, per-device retry backoff, and bounded graceful shutdown.
- Each worker runs `interceptor.listen`, grabs every current `/dev/input/event*` node whose keyboard name matches the profile, and drives `KeyboardHandler.tick()` on the listener thread. Keep delayed key/layer transitions monotonic and threadless; tests use fake clocks rather than sleeps.
- Profiles are strict version `1` YAML. Fragments with the same device name merge before worker startup; duplicate keys, unknown fields/events/key names, and conflicts must retain source/path diagnostics.
- Runtime profiles live outside the repository at `~/.config/macropad/profiles/`. Do not change user profiles unless explicitly requested.

## Intentional Constraints

- Device identity is keyboard name only, and all matching event nodes are attached. Structured hardware selectors are deferred.
- The listener intentionally rescans only after all matching paths are gone. Selector-based monitoring and reacquiring a new path while another matching path remains connected are deferred; do not implement them without a concrete requirement.
- Actions are trusted shell strings executed detached with `shell=True`; explicit argument-array actions were declined. Preserve the per-worker limit of eight concurrent actions and drop rather than queue actions at the limit.
- Notification initialization is optional: headless startup must continue when no session bus or notification service exists.

## Service Operations

- The checked-in unit is `systemd/macropad.service.in`; `tools/render_systemd_unit.py` safely renders checkout paths. Use `make systemd` to validate and install it instead of editing `~/.config/systemd/user/macropad.service` directly.
- The service runs this checkout's `.venv/bin/macropad`, not the user-level command installed by `make install-editable`; synchronize `.venv` before restarting it.
- After runtime changes, use `make restart`, then verify with `make status` or `journalctl --user -u macropad.service`. The unit expects cooperative SIGTERM shutdown, `KillMode=mixed`, and a 10-second stop timeout.
