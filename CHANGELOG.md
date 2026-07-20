# Changelog

All notable user-facing changes to Macropad are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Marked devices with profiles in `macropad monitor` listings.

## [0.2.1] - 2026-07-20

### Fixed

- Made guided key detection select the primary key from modifier key combinations.

## [0.2.0] - 2026-07-19

### Added

- Added optional profile timing settings for multi-tap resolution and one-shot layer timeouts.
- Added a global `--no-notifications` option that can be persisted in the generated systemd service.
- Added first-class momentary and toggle layer modes.
- Added inline layer command shorthand equivalent to an `up` action.

### Changed

- Moved desktop notification dependencies to the optional `notifications` package extra.
- Made notification backend loading lazy and stopped retrying after a backend failure.
- Changed active layers to fall back to base bindings by default, with per-layer `fallback: none`
  available to preserve layer-only behavior.

### Fixed

- Prevented disabled notifications from producing misleading remediation in `macropad doctor`.

## [0.1.0] - 2026-07-19

### Added

- Added Linux evdev keyboard interception by exact device name, including multi-node devices,
  disconnect handling, hotplug recovery, and per-device worker processes.
- Added strict version 1 YAML profiles with shorthand commands, `down`, `up`, `hold`, `double_tap`,
  and `triple_tap` events, persistent and one-shot layers, inline layers, and mergeable fragments.
- Added transactional profile loading, editor-safe automatic reloads, per-device restart backoff, and
  graceful bounded shutdown while preserving the last valid configuration after reload failures.
- Added detached trusted-shell action execution with an eight-action per-worker limit, contextual
  runtime logging, and opt-in action output debugging.
- Added `validate`, `doctor`, `monitor`, `init`, `status`, and `service` command workflows alongside
  foreground listening and global verbose/debug logging controls.
- Added XDG-aware profile discovery with the `~/.config/macropad/profiles/` default and legacy
  fallback behavior.
- Added desktop notifications for layer transitions and profile reload results, with nonfatal
  backend initialization for headless sessions.
- Added atomic systemd user-service installation and removal, live journal access, runtime worker
  status over a protected local socket, and cooperative SIGTERM handling.
- Added isolated wheel, service, guided-initialization, and systemd smoke tests plus CI coverage for
  Python 3.10 through 3.14.
- Published the `poor-mans-macropad` distribution to PyPI with `macropad` console and module entry
  points, MIT licensing, release automation, and artifact verification.

[Unreleased]: https://github.com/rafaelglikis/macropad/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/rafaelglikis/macropad/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/rafaelglikis/macropad/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/rafaelglikis/macropad/releases/tag/v0.1.0
